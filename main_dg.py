import os
import numpy as np
import time
from module.ExifData import *
from module.EoData import *
from module.Boundary import boundary
from module.BackprojectionResample import rectify_plane_parallel, createGeoTiff
from rich.console import Console
from rich.table import Table
from pyproj import CRS
from pyproj.aoi import AreaOfInterest
from pyproj.database import query_utm_crs_info

def generation_utmcrs(lat,lon):
    utm_crs_list = query_utm_crs_info(
        datum_name="WGS 84",
        area_of_interest=AreaOfInterest(
            west_lon_degree=lat,
            south_lat_degree=lon,
            east_lon_degree=lat,
            north_lat_degree=lon,
        ),
    )
    utm_crs = CRS.from_epsg(utm_crs_list[0].code)
    return utm_crs

console = Console()

input_folder = 'Data'
ground_height = 0   # unit: m
sensor_width = 6.3  # unit: mm, Mavic
# sensor_width = 13.2  # unit: mm, P4RTK
# sensor_width = 17.3  # unit: mm, Inspire
epsg = 5186     # editable
gsd = 0.1   # unit: m, set 0 to compute automatically

if __name__ == '__main__':
    for root, dirs, files in os.walk(input_folder):
        files.sort()
        for file in files:
            image_start_time = time.time()

            filename = os.path.splitext(file)[0]
            extension = os.path.splitext(file)[1]
            file_path = root + '/' + file
            dst = './' + filename

            if extension == '.JPG' or extension == '.jpg':
                print('Georeferencing - ' + file)
                start_time = time.time()
                image = cv2.imread(file_path, -1)

                # 1. Extract metadata from a image
                focal_length, orientation, eo, maker = get_metadata(file_path)  # unit: m, _, ndarray
                lon,lat = eo[:2]
                epsg =  generation_utmcrs(lat,lon)

                # 2. Restore the image based on orientation information
                restored_image = restoreOrientation(image, orientation)

                image_rows = restored_image.shape[0]
                image_cols = restored_image.shape[1]

                pixel_size = sensor_width / image_cols  # unit: mm/px
                pixel_size = pixel_size / 1000  # unit: m/px

                eo = geographic2plane(eo, epsg)
                opk = rpy_to_opk(eo[3:], maker)
                eo[3:] = opk * np.pi / 180   # degree to radian
                R = Rot3D(eo)

                console.print(
                    f"EOP: {eo[0]:.2f} | {eo[1]:.2f} | {eo[2]:.2f} | {eo[3]:.2f} | {eo[4]:.2f} | {eo[5]:.2f}\n"
                    f"Focal Length: {focal_length * 1000:.2f} mm, Maker: {maker}",
                    style="blink bold red underline")
                georef_time = time.time() - start_time
                console.print(f"Georeferencing time: {georef_time:.2f} sec", style="blink bold red underline")

                print('DEM & GSD')
                start_time = time.time()
                # 3. Extract a projected boundary of the image
                bbox = boundary(restored_image, eo, R, ground_height, pixel_size, focal_length)

                # 4. Compute GSD & Boundary size
                # GSD
                if gsd == 0:
                    gsd = (pixel_size * (eo[2] - ground_height)) / focal_length  # unit: m/px
                # Boundary size
                boundary_cols = int((bbox[1, 0] - bbox[0, 0]) / gsd)
                boundary_rows = int((bbox[3, 0] - bbox[2, 0]) / gsd)

                console.print(f"GSD: {gsd * 100:.2f} cm/px", style="blink bold red underline")
                dem_time = time.time() - start_time
                console.print(f"DEM time: {dem_time:.2f} sec", style="blink bold red underline")

                print('Rectify & Resampling')
                start_time = time.time()
                b, g, r, a = rectify_plane_parallel(bbox, boundary_rows, boundary_cols, gsd, eo, ground_height,
                                                    R, focal_length, pixel_size, image)
                rectify_time = time.time() - start_time
                console.print(f"Rectify time: {rectify_time:.2f} sec", style="blink bold red underline")

                # 8. Create GeoTiff
                print('Save the image in GeoTiff')
                start_time = time.time()
                createGeoTiff(b, g, r, a, bbox, gsd, epsg, boundary_rows, boundary_cols, dst)
                # create_pnga_optical(b, g, r, a, bbox, gsd, epsg, dst)   # for test
                write_time = time.time() - start_time
                console.print(f"Write time: {write_time:.2f} sec", style="blink bold red underline")

                processing_time = time.time() - image_start_time
                console.print(f"Process time: {processing_time:.2f} sec", style="blink bold red underline")

                table = Table(show_header=True, header_style="bold magenta")
                table.add_column("Image", style="dim", width=12)
                table.add_column("Georeferencing", justify="right")
                table.add_column("DEM", justify="right")
                table.add_column("Rectify", justify="right")
                table.add_column("Write", justify="right")
                table.add_column("Processing", justify="right")
                table.add_row(
                    filename, str(round(georef_time, 5)), str(round(dem_time, 5)), str(round(rectify_time, 5)),
                    str(round(write_time, 5)), str(round(processing_time, 5))
                )
                console.print(table)
