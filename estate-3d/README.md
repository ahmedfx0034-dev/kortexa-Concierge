# 3D Property Showroom (demo)

A static Three.js site. Visitors can:

- **Explore the estate in 3D.** Every listing is a 3D house on a street. Drag to orbit, pinch or scroll to zoom, and tap a house or its price pin to see its details.
- **Step inside.** Open a **floor plan** (dollhouse) view of the home with the roof removed and labels on every room, or switch to **Walk inside** for a first-person tour. On desktop you move with WASD or the arrow keys, and on phones and tablets with a joystick. In both modes you can tap the floor to walk to that spot.
- **Book a viewing** from any listing (demo form, not wired up yet).

## Editing listings
Everything comes from `listings.js`. Each listing has a house `style` (villa, bungalow, townhouse or apartment), colours, and a `rooms` list. The interior, walls, doors, windows and furniture are generated from that list.

## Running locally
Serve the folder with any static server, e.g. `npx serve estate-3d`. No build step is needed.
