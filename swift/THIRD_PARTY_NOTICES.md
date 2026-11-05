# Swift / native port notices

MoonLabeler Swift retains the main project's GPL-3.0-or-later licence and data attribution. This document describes the Swift/native runtime only. See this directory's [LICENSE](LICENSE), [DATA_SOURCES.md](DATA_SOURCES.md) and [ACKNOWLEDGEMENTS.md](ACKNOWLEDGEMENTS.md) for the licence, catalogue, names, albedo, landing sites and inherited algorithm sources. The Python version keeps its documentation separately in the parent project.

The native application incorporates these additional components:

- OpenCV, including EdgeDrawing: Apache-2.0. Source revisions and archive digests are pinned in `Native/build.command`. Licence: `Licenses/OpenCV.txt`.
- libjpeg-turbo 3.1.2, built from OpenCV's bundled source: IJG / modified BSD / zlib terms. See `Licenses/libjpeg-turbo.md` and `Licenses/libjpeg-IJG.txt`. This software is based in part on the work of the Independent JPEG Group.
- CSPICE (NAIF / NASA Jet Propulsion Laboratory): integrated library modules for SPICE ephemeris and lunar frames. The application is an independent tool, not an official NAIF toolkit redistribution. See `Licenses/NAIF-rules.html` and <https://naif.jpl.nasa.gov/naif/rules.html> for use, redistribution and warranty terms. No NASA, JPL or Caltech endorsement is implied.
  The input-only native integration configures the pinned f2c runtime to open existing input kernels read-only, rather than trying read/write access first. The kernels and ephemeris algorithms are unchanged.
- ERFA 2.0.1 (NumFOCUS Foundation): BSD licence; derived, with permission, from the IAU SOFA library. See `Licenses/ERFA.txt`. ERFA and this application are not the IAU SOFA library.
- CFITSIO 4.6.4 (NASA / HEASARC): FITS file reading. See `Licenses/CFITSIO.txt`.
- libarchive: macOS supplies the library at runtime; copied public headers retain their copyright and BSD notices in `Native/vendor/libarchive/`. Those headers are included with the application notices.
- OpenCC Simplified-to-Traditional character and phrase dictionaries: see `Licenses/OpenCC.txt`. Only dictionary data is used; conversion runs in Swift.

Scientific data are separate from executable code: JPL DE421 and NAIF lunar orientation kernels, the USGS/IAU and LPND name data, NASA SVS albedo and hourly frames, and LRO/LOLA DEM. The default personal build bundles the basic DEM and ephemeris for offline use. Higher-resolution DEM and downloaded NASA frames remain user-managed data.
