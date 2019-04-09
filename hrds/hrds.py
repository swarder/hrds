from __future__ import print_function
from .raster import RasterInterpolator
from .raster_buffer import CreateBuffer
import os
from shutil import copyfile
import tempfile
try:
    from itertools import izip as zip
except ImportError:  # will be 3.x series
    pass

# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.
#
# Copyright Jon Hill, University of York, jon.hill@york.ac.uk

# create a hierarchy of rasters to pull data from, smoothly blending
# between them


class HRDSError(Exception):
    # any error generated by the RasterInterpolator object:

    pass


class HRDS(object):
    """
    The main HRDS class. Create a raster stack and initialise::

        bathy = HRDS("gebco_uk.tif",
             rasters=("emod_utm.tif",
                      "marine_digimap.tif"),
             distances=(10000, 5000),
             minmax=None)
        bathy.set_bands()

    The first argument is the base raster filename. `rasters` is a list
    of raster filenames, with corresponding `distances` over which to
    create the buffer. Distances are in the same units as the rasters.
    The min/max argument allows you to specify a minimum or maximum
    (or both!) values when returning data. This is useful for ocean
    simulations where you want a minimum depth to prevent "drying".
    To set this, do::

        bathy = HRDS("gebco_uk.tif",
             rasters=("emod_utm.tif",
                      "marine_digimap.tif"),
             distances=(10000, 5000),
             minmax=[[None,-5],[None,-3],[None,None]])

    which would set a maximum depth of -5m on the gebco data (-ve = below
    sea level, +ve above), maximum of -3m on the emod data and no limits
    on the marine_digimap data. You must supply the same number of min-max
    pairs are there are total rasters. Temporary buffer files will be created
    and deleted at clean up

    If is possible to supply the buffer rasters directly (e.g. if you want
    to use different distances on each edge of your raster, or some other
    such thing). Buffer extent must match or exceed the corresponding raster
    extent::

        bathy = HRDS("gebco_uk.tif",
             rasters=("emod_utm.tif",
                      "marine_digimap.tif"),
             buffers=(buffer1.tif,
                      buffer2.tif,
                      buffer3.tif))
        bathy.set_bands()

    Once set up, you can ask for data at any point::

        bathy.get_val(100,100)
    """
    def __init__(self, baseRaster, rasters=None, distances=None,
                 buffers=None, minmax=None, saveBuffers=False):
        """
        baseRaster is the low res raster filename across whole domain.
        rasters is a list of filenames of the other rasters in priority order.
        distances is the distance to create a buffer (in same units as
        corresponding raster) for each.
        buffers is a lost of buffer filenames in the same order as rasters
        if created already. In this case, don't supply distances.
        """

        if distances is None:
            if len(rasters) != len(buffers):
                raise HRDSError("You have "+str(len(rasters)) +
                                "rasters and "+str(len(buffers)) +
                                "buffers. They should match")
        else:
            if len(rasters) != len(distances):
                raise HRDSError("You have "+str(len(rasters)) +
                                "rasters and "+str(len(distances)) +
                                "distances. They should match")

        if minmax is not None:
            if len(rasters)+1 != len(minmax):
                raise HRDSError("Please supply same number of minmax values" +
                                "as the total number of rasters, inc. base." +
                                "You gave me: "+str(len(minmax))+" min/max" +
                                "and I expected: "+str(len(rasters)+1))

        if minmax is None:
            self.baseRaster = RasterInterpolator(baseRaster)
        else:
            self.baseRaster = RasterInterpolator(baseRaster, minmax[0])
        self.raster_stack = []
        for i, r in enumerate(rasters):
            if minmax is None:
                self.raster_stack.append(RasterInterpolator(r))
            else:
                self.raster_stack.append(RasterInterpolator(r, minmax[i+1]))
        self.buffer_stack = []
        # the user is asking us to create the buffer files
        if buffers is None:
            # we create the files in a temp dir and if the user wants
            # them afterwards we copy to a sensible name
            with tempfile.TemporaryDirectory() as tmpdirname:
                for r, d in zip(rasters, distances):
                    # create buffer file name, based on raster filename
                    keep_buf_file = os.path.splitext(r)[0]+"_buffer.tif"
                    temp_buf_file = os.path.join(tmpdirname,
                                                 os.path.splitext(
                                                     os.path.basename(r))[0] +
                                                 "_buffer.tif")
                    # create buffer
                    rbuff = CreateBuffer(r, d)
                    rbuff.make_buffer(temp_buf_file)
                    # add to stack and store in memory
                    self.buffer_stack.append(RasterInterpolator(temp_buf_file))
                    # does the user also want the file saving?
                    if saveBuffers:
                        copyfile(temp_buf_file, keep_buf_file)

        else:
            # create buffer stack from filenames
            for r in buffers:
                self.buffer_stack.append(RasterInterpolator(r))

        # reverse the arrays
        self.buffer_stack.reverse()
        self.raster_stack.reverse()

    def set_bands(self, bands=None):
        """
        Performs bilinear interpolation of your raster stack
        to give a value at the requested point.

        Args:
            bands: a list of band numbers for each raster in the stack or None
                (uses the first band in each raster). Default is None.

        """

        if bands is None:
            self.baseRaster.set_band()
            for r in self.raster_stack:
                r.set_band()
            for r in self.buffer_stack:
                r.set_band()
        else:
            counter = 1
            self.baseRaster.bands(bands[0])
            for r in self.raster_stack:
                r.set_band(bands[counter])
                counter += 1
            counter = 1
            for r in self.buffer_stack:
                r.set_band(bands[counter])
                counter += 1

    def get_val(self, point):
        """
        Performs bilinear interpolation of your raster stack
        to give a value at the requested point.

        Args:
            point: a length 2 list containing x,y coordinates

        Returns:
            The value of the raster stack at that point

        Raises:
            CoordinateError: The point is outside the rasters
            RasterInterpolatorError: Generic error interpolating
                data at that point
        """
        # determine if we're in any of the rasters in the list,
        # starting from the last one
        for i, r, b in zip(range(0, len(self.raster_stack)+1),
                           self.raster_stack,
                           self.buffer_stack):
            if r.point_in(point):
                # if so, check the buffer value
                if b.get_val(point) == 1.0:
                    return r.get_val(point)
                else:
                    for rr in self.raster_stack[i+1:]:
                        # if not, find the next raster we're in, inc. the base
                        if rr.point_in(point):
                            val = r.get_val(point)*b.get_val(point) + \
                                  rr.get_val(point)*(1-b.get_val(point))
                            return val
                    # if we get here, there is no other layer,
                    # so use base raster
                    val = r.get_val(point)*b.get_val(point) + \
                        self.baseRaster.get_val(point)*(1-b.get_val(point))
                    return val

        # we're not in the raster stack, so return value from base
        return self.baseRaster.get_val(point)
