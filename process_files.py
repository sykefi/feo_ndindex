import os 
import numpy as np 
import rasterio as rio
import sys

from pathlib import Path 
from shutil import rmtree
from fastcore.script import *
from src.functions import *

import rasterio.windows as rio_windows
import rasterio.merge as rio_merge
import geopandas as gpd
from rasterio.enums import Resampling
from shapely.geometry import box
from itertools import product
import multiprocessing

import logging
logging.basicConfig(
    format='%(asctime)s %(levelname)-8s %(message)s',
    level=logging.INFO,
    datefmt='%Y-%m-%d %H:%M:%S')

"""
CLI for processing on-site normalized index mosaics. 
The files are assumed to have filename pattern 

`pta_sjp_s2ind_<ndindex>_<startdate>_<enddate>.tif`
 
and folder pattern `<datapath>/<year>/<index>/<filename>`

The base mosaic for spring is created from all available mosaics from 
April and May, while base mosaic for autumn is created from available mosaics
from mid-September to October.

Mosaics have width of 79200 pixels and height of 120000 pixels. They are processed by
9900x10000 pixel windows, which divide Finland into 8 columns and 12 rows. These windows
are collated into single mosaics at the end.
"""

def get_script_path():
    "Utility to get the path for Finnish borders"
    return os.path.dirname(os.path.realpath(sys.argv[0]))

def rio_merge_files(files_to_mosaic, outpath):
    "Merge files, used with multiprocessing.Pool"
    logging.info(f'Creating file {outpath.stem}')
    rio_merge.merge(files_to_mosaic, dst_path=outpath,
                    dst_kwds={'compress':'lzw', 'predictor':2, 'BIGTIFF':'YES'})
    return

def patch_build_overviews(fname):
    "Build overviews to mosaics, used with multiprocessing.Pool"
    logging.info(f'Building overviews for {fname.stem}')
    factors = [2**(n+1) for n in range(9)]
    dst = rio.open(fname, 'r+')
    dst.build_overviews(factors, Resampling.nearest)
    dst.update_tags(ns='rio_overview', resampling='nearest')
    dst.close()
    return 

def process_patch(outpath:Path, years:list, files:list, ndindex:str, x:int, y:int) -> None:
    """
    Process 10000x9900 patches and compute stats from them. By default, products for 
    2018, 2019, 2020 and 2021 are produced, using data from 2016 to 2021

    1. Check if the window is within Finnish borders. If not, skip it
    2. Extract 10000x9900 patches from the full mosaics 
    3. Construct basemosaics for spring (April-May) and autumn (mid-September - October). Basemosaics
       contain the pixelwise median values from the full data availability period
    4. Fill all nodata with the maximum value for the same month and pixel from two previous years
    5. Run rasterio.fill.fillnodata with maximum search distance of 100 and three iterations
    6. Fill all remaining nodata for April and May mosaics with spring basemosaic
    7. Fill all remaining nodata for October with autumn basemosaic
    8. Fill all remaining nodata for August with the mean value of July and September of the same year
    9. Collate yearly statistics
    10. Clip products to Finnish borders, if necessary.
    """
    logging.info(f'Starting with raster {x}_{y}')
    ix_path = outpath/ndindex
    base_datapath = ix_path/'base_mosaics'
    datapath = ix_path/f'testdata_{x}_{y}'
    os.makedirs(datapath, exist_ok=True)
    borders = gpd.read_file(f'{get_script_path()}/aux_data/fin_borders.shp')

    for year in years: os.makedirs(datapath/str(year), exist_ok=True)
    window = rio_windows.Window.from_slices((y, y+10000), (x, x+9900))
    for f in files:
        year = str(f).split(f'{ndindex}_')[1][:4]
        with rio.open(f) as src:
            prof = src.profile.copy()
            prof.update(
                height=window.height,
                width=window.width,
                transform= rio_windows.transform(window, src.transform),
                compress='lzw',
                predictor=2
            )
            # If window is not within Finnish borders, no need to process it
            bbox = box(prof['transform'][2],
                       prof['transform'][5]+prof['transform'][4]*window.height,
                       prof['transform'][2]+prof['transform'][0]*window.width,
                       prof['transform'][5])

            if not bbox.intersects(borders.iloc[0].geometry):
                logging.info(f'Window {x}_{y} outside Finnish borders, skipping..')
                rmtree(datapath)
                return

            with rio.open(datapath/year/f.name, 'w', **prof) as dest:
                dest.write(src.read(window=window)[0],1)
            if ndindex == 'ndbi': # For ndbi 0 can be either nodata or valid value so we need nodatamask from metadata
                with rio.open(str(f).replace('ndbi', 'meta').replace('NDBI', 'META')) as meta:
                    meta_mask = meta.read(window=window, masked=True)[0]
                with rio.open(datapath/year/f.name, 'r+') as src:
                    src.nodata = 255
                    vals = src.read()[0]
                    vals[meta_mask.mask] = 255
                    src.write(vals,1)
                
    spring_files = sorted([t for t in files if 
                           any(mon in str(t) for mon in ('0430', '0515', '0531'))])
    autumn_files = sorted([t for t in files if 
                           any(mon in str(t) for mon in ('1015', '1031'))])

    vals = []
    for f in spring_files:
        with rio.open(f) as src:
            if ndindex != 'ndbi':
                vals.append(src.read(window=window, masked=True)[0])
            else:
                with rio.open(str(f).replace('ndbi', 'meta').replace('NDBI', 'META')) as meta:
                    meta_mask = meta.read(window=window, masked=True)[0]
                tmp = src.read(window=window)[0]
                tmp[meta_mask.mask] = 255
                vals.append(np.ma.array(src.read(window=window)[0], mask=meta_mask.mask))
                prof['nodata'] = 255

    vals = np.ma.array(vals)
    vals = np.ma.median(vals, axis=0)
    with rio.open(base_datapath/f'base_spring_{x}_{y}.tif', 'w', **prof) as dest:
        dest.write(vals, 1)

    vals = []
    for f in autumn_files:
        with rio.open(f) as src:
            if ndindex != 'ndbi':
                vals.append(src.read(window=window, masked=True)[0])
            else:
                with rio.open(str(f).replace('ndbi', 'meta').replace('NDBI', 'META')) as meta:
                    meta_mask = meta.read(window=window, masked=True)[0]
                tmp = src.read(window=window)[0]
                tmp[meta_mask.mask] = 255
                vals.append(np.ma.array(src.read(window=window)[0], mask=meta_mask.mask))

    vals = np.ma.array(vals)
    vals = np.ma.median(vals, axis=0)
    with rio.open(base_datapath/f'base_autumn_{x}_{y}.tif', 'w', **prof) as dest:
        dest.write(vals, 1)

    logging.info(f'Filling nodata values for {x}_{y}')

    filled_path = ix_path/f'interp_{x}_{y}'

    fillyears = [
        2018,
        2019,
        2020,
        2021
    ]

    fill_prev_years(datapath, filled_path, fillyears)
    if ndindex != 'ndbi':
        fill_nodata(filled_path)
    fill_base(filled_path, base_datapath/f'base_spring_{x}_{y}.tif')
    fill_base(filled_path, base_datapath/f'base_autumn_{x}_{y}.tif')
    rmtree(datapath)
    fill_august(filled_path)

    logging.info(f'Creating statistics rasters {x}_{y}')
    statspath = ix_path/f'stats_{x}_{y}'
    make_stats(filled_path, statspath)

    if not bbox.within(borders.iloc[0].geometry):
        logging.info(f'Clipping rasters {x}_{y}')
        # Clip rasters within Finnish borders
        clip_rasters(filled_path, borders, fillyears)
        clip_rasters(statspath, borders, fillyears)
    logging.info(f'Finished with raster {x}_{y}')
    return


@call_parse
def main(ndindex:Param("""Normalized difference index to use, 
                       must be one of ndvi, ndmi, ndbi, ndbi or ndsi.
                       Default ndvi""", str, default='ndvi',
                       choices=['ndvi', 'ndmi', 'ndbi', 'ndbi', 'ndsi']),
         outpath:Param('Path to save generated data to. default "."',
                       str, default='.'),
         inpath:Param('Path that contains all the required files', str)):

    inpath = Path(inpath)
    outpath = Path(outpath)
    years = [2016, 2017,2018,2019,2020,2021]
    files = []
    for year in years:
        files.extend([inpath/f'{year}/{ndindex.upper()}/{f}'
                      for f in os.listdir(inpath/f'{year}/{ndindex.upper()}')
                      if '15' not in f])
    files = [f for f in files if str(f).endswith('tif')]

    ix_path = outpath/ndindex
    base_datapath = ix_path/'base_mosaics'
    os.makedirs(base_datapath, exist_ok=True)

    inputs = [(outpath, years, files, ndindex, x, y) for x, y in 
               product(range(0, 79200, 9900), range(0,120000,10000))]

    with multiprocessing.Pool(5) as pool:
        pool.starmap(process_patch, inputs)

    
    interp_folders = [f for f in os.listdir(ix_path) if 'interp_' in f]
    stats_folders = [f for f in os.listdir(ix_path) if 'stats_' in f]
    final_interp = ix_path/'interp'
    os.makedirs(final_interp, exist_ok=True)
    final_stats = ix_path/'stats'
    os.makedirs(final_stats, exist_ok=True)

    spring_bases = [base_datapath/f for f in os.listdir(base_datapath) if 'spring' in f]
    autumn_bases = [base_datapath/f for f in os.listdir(base_datapath) if 'autumn' in f]
    
    with multiprocessing.Pool(2) as pool:
        pool.starmap(rio_merge_files, [(spring_bases, ix_path/'base_spring.tif'),
                                       (autumn_bases, ix_path/'base_autumn.tif')])
    
    rmtree(base_datapath)

    fillyears = [
        2018,
        2019,
        2020,
        2021
        ]

    merge_inps = []

    for year in fillyears:
        os.makedirs(final_interp/str(year), exist_ok=True)
        os.makedirs(final_stats/str(year), exist_ok=True)
        merge_inps.extend([([ix_path/fol/str(year)/f for fol in stats_folders], final_stats/str(year)/f) 
                             for f in os.listdir(ix_path/stats_folders[0]/str(year))])
        merge_inps.extend([([ix_path/fol/str(year)/f for fol in interp_folders], final_interp/str(year)/f) 
                             for f in os.listdir(ix_path/interp_folders[0]/str(year))])

    with multiprocessing.Pool(8) as pool:
        pool.starmap(rio_merge_files, merge_inps)
    
    for f in interp_folders: rmtree(ix_path/f)

    for f in stats_folders: rmtree(ix_path/f)

    logging.info('Building overviews')
    # Build overviews
    base_fns = [ix_path/'base_spring.tif', ix_path/'base_autumn.tif'] 
    stats_fns = [final_stats/year/f for year in os.listdir(final_stats) for f in os.listdir(final_stats/year)]
    interp_fns = [final_interp/year/f for year in os.listdir(final_interp) for f in os.listdir(final_interp/year)]

    overview_inps = base_fns + stats_fns + interp_fns
    with multiprocessing.Pool(8) as pool:
        pool.map(patch_build_overviews, overview_inps)
    logging.info('Finished')