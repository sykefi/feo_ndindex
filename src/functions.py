import rasterio as rio
from rasterio.fill import fillnodata
from pathlib import Path
import numpy as np
import os
import geopandas as gpd
import rasterio.mask as rio_mask
import geopandas as gpd

"""
Functions that fill gaps in ndindex mosaics and collate stats from them
"""

__all__ = ['fill_prev_years', 'fill_nodata', 'fill_base', 
           'fill_august', 'make_stats', 'clip_rasters', 'clip_raster']

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

def fill_nodata(datapath:Path) -> None:
    """Run `rasterio.fill.fillnodata` to mosaic with search distance of 100 pixels, 3 iterations"""
    for f in os.listdir(datapath): 
        for mos in [m for m in os.listdir(datapath/str(f)) if m.endswith('tif')]:
            with rio.open(datapath/f/mos) as src:
                prof = src.profile
                arr = src.read(1)
                arr_filled = fillnodata(arr, mask=src.read_masks(1), 
                                        max_search_distance=100, smoothing_iterations=3)
        with rio.open(datapath/f/mos, 'w', **prof) as dest:
            dest.write_band(1, np.clip(arr_filled,0,200)) # Sometimes fillnodata fills in values that are too large
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

def fill_august(datapath:Path) -> None:
    """Fill August mosaic with the mean value of July and September of the same year"""
    for f in os.listdir(datapath):
        aug_file = [fname for fname in os.listdir(datapath/str(f)) if '08' in fname and fname.endswith('tif')][0]
        with rio.open(datapath/str(f)/aug_file) as src:
            prof = src.profile
            aug = src.read(masked=True)[0]
        jul_file = [fname for fname in os.listdir(datapath/str(f)) if '07' in fname and fname.endswith('tif')][0]
        with rio.open(datapath/str(f)/jul_file) as src:
            jul = src.read(masked=True)[0]
        sep_file = [fname for fname in os.listdir(datapath/str(f)) if '09' in fname and fname.endswith('tif')][0]
        with rio.open(datapath/str(f)/sep_file) as src:
            sep = src.read(masked=True)[0]
        aug.data[aug.mask] = np.ma.array([jul, sep]).mean(axis=0)[aug.mask]
        with rio.open(datapath/str(f)/aug_file, 'w', **prof) as dest:
            dest.write_band(1, aug.data)
    return

def make_amplitude(mosaics:np.ndarray, basepath:Path) -> np.ndarray:
    pass

def make_stats(datapath:Path, outpath:Path, base_mos:Path) -> None:
    """
    Generate yearly stats for the mosaic. The generated stats are
    * Yearly mean, datatype uint8
    * Yearly median, datatype uint8
    * Yearly min, datatype uint8
    * Yearly max, datatype uint8
    * Yearly sum, datatype uint16
    * Amplitude (pixelwise max - base), datatype uint8
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
        prof.update({'dtype':'int16',
                     'nodata': -999})
        with rio.open(outpath/str(f)/'amp.tif', 'w', **prof) as dest:
            with rio.open(base_mos) as src:
                basevals = src.read()[0]
            dest.write(mosaics.max(axis=0).astype(np.int16)-basevals.astype(np.int16), 1)
        prof.update({'dtype':'uint16',
                     'nodata': 65535})
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