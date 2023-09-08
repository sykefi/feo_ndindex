import rasterio as rio
from pathlib import Path
import numpy as np
import os
import geopandas as gpd
import rasterio.mask as rio_mask
import geopandas as gpd
from .numpy_utils import * 

"""
Functions that fill gaps in ndindex mosaics and collate stats from them
"""

__all__ = ['generate_base', 'fill_prev_years','fill_base', 
           'fill_adjacent_months', 'make_stats', 'clip_rasters', 'clip_raster']

def generate_base(datapath:Path, quantile:int=10) -> np.ndarray:
    """Generate base value mosaic, where base is `quantile` of the full study period"""
    mosaics = []
    years = os.listdir(datapath)
    for y in years:
        for mos in [m for m in os.listdir(datapath/y) if m.endswith('tif')]:
            with rio.open(datapath/y/mos) as src:
                mosaics.append(src.read()[0])
    mosaics = np.array(mosaics).astype(np.float32)
    mosaics[mosaics == 0] = np.nan
    return nan_percentile(mosaics, quantile)[0]

def fill_prev_years(datapath:Path, outpath:Path, fillyears:list) -> None:
    """Fill nodata values for as single month with maximum value of the same month
    from two previous years"""
    os.makedirs(outpath, exist_ok=True)
    for f in fillyears: 
        os.makedirs(outpath/str(f), exist_ok=True)
        for mos in [m for m in os.listdir(datapath/str(f)) if m.endswith('tif')]:
            with rio.open(datapath/str(f)/mos) as src:
                vals = src.read(masked=True)[0]
                meta = src.meta
                nodataval = src.nodata
            try:
                with rio.open(datapath/str(f-1)/mos.replace(str(f), str(f-1))) as src_1:
                    vals_1 = src_1.read(masked=True)[0]
            except:
                vals_1 = np.full(vals.shape, fill_value=nodataval)
            try:
                with rio.open(datapath/str(f-2)/mos.replace(str(f), str(f-2))) as src_2:
                    vals_2 = src_2.read(masked=True)[0]
            except:
                vals_2 = np.full(vals.shape, fill_value=nodataval)
            stack = np.ma.array([vals_1, vals_2],fill_value=nodataval)
            maxvals = stack.max(axis=0)
            maxvals.data[maxvals.mask] = nodataval
            vals.data[vals.mask] = maxvals.data[vals.mask]
            with rio.open(outpath/str(f)/mos, 'w', **meta) as dest:
                dest.write(vals.data, 1)
    return

def fill_base(datapath:Path, base_mosaic:str) -> None:
    "Fill April, May and October mosaics with basedata mosaic"
    if 'spring' in str(base_mosaic): base_months = ['04','05']
    elif 'autumn' in str(base_mosaic): base_months = ['10']
    else: 
        print('Faulty base mosaic, skipping')
        return
    for f in os.listdir(datapath):
        with rio.open(base_mosaic) as wm:
            wm_vals = wm.read()[0]
            for mos in [m for m in os.listdir(datapath/f) 
                        if any(base_month in m for base_month in base_months)
                        and m.endswith('tif')]:
                with rio.open(datapath/f/mos) as src:
                    data = src.read(masked=True)[0]
                    prof = src.profile
                data.data[data.mask] = wm_vals[data.mask]
                with rio.open(datapath/f/mos, 'w', **prof) as dest:
                    dest.write_band(1, data.data)
    return

def fill_adjacent_months(datapath:Path, month:int) -> None:
    """Fill `month` mosaic with the mean value of previous and next month of the same year"""
    for f in os.listdir(datapath):
        cur_file = [fname for fname in os.listdir(datapath/str(f)) if f'{month:02d}' in fname and fname.endswith('tif')][0]
        with rio.open(datapath/str(f)/cur_file) as src:
            prof = src.profile
            cur = src.read(masked=True)[0]
        prev_file = [fname for fname in os.listdir(datapath/str(f)) if f'{month-1:02d}' in fname and fname.endswith('tif')][0]
        with rio.open(datapath/str(f)/prev_file) as src:
            prev = src.read(masked=True)[0]
        nxt_file = [fname for fname in os.listdir(datapath/str(f)) if f'{month+1:02d}' in fname and fname.endswith('tif')][0]
        with rio.open(datapath/str(f)/nxt_file) as src:
            nxt = src.read(masked=True)[0]
        cur.data[cur.mask] = np.ma.array([prev, nxt]).mean(axis=0)[cur.mask]
        with rio.open(datapath/str(f)/cur_file, 'w', **prof) as dest:
            dest.write_band(1, cur.data)
    return

def make_stats(datapath:Path, outpath:Path, base_mos:Path) -> None:
    """
    Generate yearly stats for the mosaic. The generated stats are
    * Yearly mean, datatype uint8
    * Yearly median, datatype uint8
    * Yearly min, datatype uint8
    * Yearly max, datatype uint8
    * Yearly sum, datatype int16
    * Yearly quantiles: 10 and 25 so far, datatype uint8
    * Amplitude (pixelwise max - yearly_25 quantile), datatype int16
    """
    os.makedirs(outpath, exist_ok=True)
    for f in os.listdir(datapath): 
        os.makedirs(outpath/f, exist_ok=True)
        mosaics = []
        for mos in [m for m in os.listdir(datapath/str(f)) if m.endswith('tif')]:
            with rio.open(datapath/str(f)/mos) as src:
                prof = src.profile
                data = src.read(masked=True)[0]
            mosaics.append(data)
        mosaics = np.ma.array(mosaics)
        with rio.open(outpath/str(f)/'mean.tif', 'w', **prof) as dest:
            dest.write(mosaics.mean(axis=0),1)
        with rio.open(outpath/str(f)/'median.tif', 'w', **prof) as dest:
            dest.write(np.ma.median(mosaics, axis=0),1)
        with rio.open(outpath/str(f)/'min.tif', 'w', **prof) as dest:
            dest.write(mosaics.min(axis=0),1)
        with rio.open(outpath/str(f)/'max.tif', 'w', **prof) as dest:
            dest.write(mosaics.max(axis=0),1)
        quantiles = nan_percentile(mosaics, [10,25])
        with rio.open(outpath/str(f)/'quantile_10.tif', 'w', **prof) as dest:
            dest.write(quantiles[0], 1)
        with rio.open(outpath/str(f)/'quantile_25.tif', 'w', **prof) as dest:
            dest.write(quantiles[1], 1)
        prof.update({'dtype':'int16',
                     'nodata': -999})
        with rio.open(outpath/str(f)/'amp.tif', 'w', **prof) as dest:
            dest.write(mosaics.max(axis=0).astype(np.int16)-quantiles[1].astype(np.int16), 1)
        mosaics = mosaics.astype(np.int16)
        with rio.open(outpath/str(f)/'sum.tif', 'w', **prof) as dest:
            dest.write(mosaics.sum(axis=0), 1)
    return 

def clip_raster(datapath:Path, borders:gpd.GeoDataFrame) -> None:
    with rio.open(datapath) as src:
        out_im, out_transform = rio_mask.mask(src, borders.geometry, crop=True)
        prof = src.profile
    prof.update(compress='lzw',
                predictor=2,
                BIGTIFF='YES',
                height=out_im.shape[1],
                width=out_im.shape[2],
                transform=out_transform)
    with rio.open(datapath, 'w', **prof) as dest:
        dest.write(out_im)
    return

def clip_rasters(datapath:Path, borders:gpd.GeoDataFrame, fillyears:list) -> None:
    for year in fillyears:
        for f in os.listdir(datapath/str(year)):
            clip_raster(datapath/str(year)/f, borders)
    return