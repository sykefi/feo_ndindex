Yearly gap-free Sentinel-2 image index mosaics
================

Scripts presented here are used to generate yearly gap-free Sentinel-2 image index mosaics by further processing S2ind-mosaics [https://ckan.ymparisto.fi/dataset/sentinel-2-image-index-mosaics-s2ind-sentinel-2-kuvamosaiikit-s2ind](https://ckan.ymparisto.fi/dataset/sentinel-2-image-index-mosaics-s2ind-sentinel-2-kuvamosaiikit-s2ind) for the full months. For a single index, the following mosaics are produced:

- Yearly maximum value
- Yearly minimum value
- Yearly mean
- Yearly median
- Yearly amplitude (pixelwise maximum - 10-quantile of three-year period)
- Yearly sum
- Yearly 10-quantile and 25-quantile
- Monthly mosaics for April, May, June, July, August, September and
  October

These mosaics are not produced at once, but S2ind mosaics are first tiled into a 12x8 grid, which are again combined after the processing. During processing, all nodata values are ignored. The processing steps are the following:

1.  Two base mosaics are constructed, one for spring and one for autumn. The values for these mosaics are median values of all available data (2016 to 2022). Spring mosaic is constructed from dates between 1.4. and 31.5., while the autumn mosaic is constructed from dates between 15.9. and 31.10.
2.  All gaps in mosaics are filled with the maximum value of the same month and pixel from two previous years
3.  All remaining nodata for April and May mosaics are filled with corresponding values from the base spring mosaic
4.  All remaining nodata for October are filled with corresponding values from the base autumn mosaic
5.  All remaining nodata for May, June, July, August and September are filled with the mean value of the adjacent months of the same year
6.  Yearly statistics are collated
7.  All produced mosaics are clipped to Finnish borders

Nodatavalues are 0 for other indices than NDBI, where nodatavalue is 255. 

The pixel size for the dataset is 10m. Datatype is unsigned 8 bit integer for all mosaics except yearly sum, whose datatype is unsigned 16bit integer.


## Installation

Install [miniconda](https://docs.conda.io/en/main/miniconda.html) and run

``` bash
conda env create -f environment.yml 
```

## Usage

Example on the workflow is provided in [Processing_flow.ipynb](Processing_flow.ipynb). Also, provided that you have access to the full PTA-mosaics on your own machine `process_files.py` runs the whole processing chain for them.
