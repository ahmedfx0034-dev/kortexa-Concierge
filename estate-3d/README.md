# MED Property 3D showroom

A static Three.js site that shows only **MED Property's real listings**. They load live from the same database that powers medpropertygh.com, using the site's public read-only key, so the 3D site updates on its own whenever a listing is added, edited or removed there.

Visitors can:

- **Browse the estate map.** Every current listing is a 3D house on a street grid. Filter by For Sale, For Rent, Short Stay or Commercial, and by region. Drag to orbit, pinch or scroll to zoom, and tap a house or its price pin.
- **See the real listing.** Each listing shows its photo gallery, price, bedrooms, bathrooms, description, features and video tour link exactly as on medpropertygh.com, with WhatsApp and Book-a-viewing buttons.
- **Step inside.** A walkable 3D interior is generated from the listing's room count, with a floor-plan view and a first-person walk. The room layout is an illustration, because the database doesn't store floor plans.

## Files
- `listings.js` loads the listings and maps them to 3D styles. It also holds the agency's contact details.
- `app.js` contains the 3D engine.
- `index.html` contains the UI.

## Running locally
Serve the folder with any static server, e.g. `npx serve estate-3d`. No build step is needed.
