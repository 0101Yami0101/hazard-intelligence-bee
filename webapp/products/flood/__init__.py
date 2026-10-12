"""FloodSense — the flood module.

Deliberately the SAME two-part shape as SlideSense, because the physics splits
the same way:

    flood risk = where water collects (terrain, static)
               x how much is coming   (river discharge / catchment rain, daily)

⚠️ Status is "building" and the page says so in as many words. The honest
position is that the static half is computable from data already on disk,
while the daily half is thin: GloFAS resolves the large rivers only, and its
reanalysis archive has not been downloaded yet. A page that showed a colourful
statewide flood map today would be inventing the half we do not have.
"""
