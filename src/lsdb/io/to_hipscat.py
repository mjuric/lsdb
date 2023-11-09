import dataclasses
from copy import copy
from importlib.metadata import version
from typing import Any, Dict, Union

import hipscat as hc
from hipscat.io import FilePointer
from hipscat.pixel_math import HealpixPixel

from lsdb.io import file_io
from lsdb.types import HealpixInfo


# pylint: disable=W0212
def to_hipscat(
    catalog,
    base_catalog_path: str,
    catalog_name: Union[str | None] = None,
    storage_options: Union[Dict[Any, Any], None] = None,
):
    """Writes a catalog to disk, in HiPSCat format. The output catalog comprises
    partition parquet files and respective metadata, as well as JSON files detailing
    partition, catalog and provenance info.

    Args:
        catalog (Catalog): A catalog to export
        base_catalog_path (str): Location where catalog is saved to
        catalog_name (str): The name of the output catalog
        storage_options (dict): Dictionary that contains abstract filesystem credentials
    """
    # Create base directory
    base_catalog_dir_fp = hc.io.get_file_pointer_from_path(base_catalog_path)
    hc.io.file_io.make_directory(base_catalog_dir_fp)
    # Save partition parquet files
    pixel_to_partition_size_map = write_partitions(catalog, base_catalog_dir_fp, storage_options)
    # Save parquet metadata
    hc.io.write_parquet_metadata(base_catalog_path, storage_options)
    # Save partition info
    partition_info = _get_partition_info_dict(pixel_to_partition_size_map)
    hc.io.write_partition_info(base_catalog_dir_fp, partition_info, storage_options)
    # Save catalog info
    new_hc_structure = create_modified_catalog_structure(
        catalog.hc_structure,
        base_catalog_path,
        catalog_name if catalog_name else catalog.hc_structure.catalog_name,
        total_rows=sum(pi[0] for pi in partition_info.values()),
    )
    hc.io.write_catalog_info(
        catalog_base_dir=base_catalog_path,
        dataset_info=new_hc_structure.catalog_info,
        storage_options=storage_options,
    )
    # Save provenance info
    hc.io.write_metadata.write_provenance_info(
        catalog_base_dir=base_catalog_dir_fp,
        dataset_info=new_hc_structure.catalog_info,
        tool_args=_get_provenance_info(new_hc_structure),
        storage_options=storage_options,
    )


def write_partitions(
    catalog, base_catalog_dir_fp: FilePointer, storage_options: Union[Dict[Any, Any], None] = None
) -> Dict[HealpixPixel, int]:
    """Saves catalog partitions as parquet to disk

    Args:
        catalog (Catalog): A catalog to export
        base_catalog_dir_fp (FilePointer): Path to the base directory of the catalog
        storage_options (dict): Dictionary that contains abstract filesystem credentials

    Returns:
        A dictionary mapping each HEALPix pixel to the number of data points in it.
    """
    pixel_to_partition_size_map = {}
    for pixel, partition_index in catalog._ddf_pixel_map.items():
        partition = catalog._ddf.partitions[partition_index].compute()
        pixel_path = hc.io.paths.pixel_catalog_file(base_catalog_dir_fp, pixel.order, pixel.pixel)
        file_io.write_dataframe_to_parquet(partition, pixel_path, storage_options)
        pixel_to_partition_size_map[pixel] = len(partition)
    return pixel_to_partition_size_map


def _get_partition_info_dict(ddf_points_map: Dict[HealpixPixel, int]) -> Dict[HealpixPixel, HealpixInfo]:
    """Creates the partition info dictionary

    Args:
        ddf_points_map (Dict[HealpixPix,int]): Dictionary mapping each HealpixPixel
            to the respective number of points inside its partition

    Returns:
        A partition info dictionary, where the keys are the HEALPix pixels and
        the values are pairs where the first element is the number of points
        inside the pixel, and the second is the list of destination pixel numbers.
    """
    return {pixel: (length, [pixel.pixel]) for pixel, length in ddf_points_map.items()}


def create_modified_catalog_structure(
    catalog_structure: hc.catalog.Catalog, catalog_base_dir: str, catalog_name: str, **kwargs
) -> hc.catalog.Catalog:
    """Creates a modified version of the HiPSCat catalog structure

    Args:
        catalog_structure (hc.catalog.Catalog): HiPSCat catalog structure
        catalog_base_dir (str): Base location for the catalog
        catalog_name (str): The name of the catalog to be saved
        **kwargs: The remaining parameters to be updated in the catalog info object

    Returns:
        A HiPSCat structure, modified with the parameters provided.
    """
    new_hc_structure = copy(catalog_structure)
    new_hc_structure.catalog_name = catalog_name
    new_hc_structure.catalog_path = catalog_base_dir
    new_hc_structure.catalog_base_dir = hc.io.file_io.get_file_pointer_from_path(catalog_base_dir)
    new_hc_structure.on_disk = True
    new_hc_structure.catalog_info = dataclasses.replace(
        new_hc_structure.catalog_info, catalog_name=catalog_name, **kwargs
    )
    return new_hc_structure


def _get_provenance_info(catalog_structure: hc.catalog.Catalog) -> dict:
    """Fill all known information in a dictionary for provenance tracking.

    Returns:
        dictionary with all argument_name -> argument_value as key -> value pairs.
    """
    catalog_info = catalog_structure.catalog_info
    args = {
        "catalog_name": catalog_structure.catalog_name,
        "output_path": catalog_structure.catalog_path,
        "output_catalog_name": catalog_structure.catalog_name,
        "catalog_path": catalog_structure.catalog_path,
        "epoch": catalog_info.epoch,
        "catalog_type": catalog_info.catalog_type,
        "ra_column": catalog_info.ra_column,
        "dec_column": catalog_info.dec_column,
    }
    provenance_info = {
        "tool_name": "lsdb",
        "version": version("lsdb"),
        "runtime_args": args,
    }
    return provenance_info
