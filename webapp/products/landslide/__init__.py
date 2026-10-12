"""SlideSense — the landslide module. (Called SlopeSense until 2026-10-11;
that name now belongs to the whole platform.)

    hazard = susceptibility (where, 100 m, static)
           x trigger        (when, ~22 km, daily)

The product is the FORECAST, and a forecast is only useful somewhere. So the
Forecast page is built around ONE location: anything the visitor searches for,
or their own position if they ask for it. The statewide picture is real but it
is a management view, folded away under the local one.
"""
