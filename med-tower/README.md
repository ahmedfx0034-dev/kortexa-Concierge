# MED Residences: "Choose your floor" concept

A single-page site built on the tower-blueprint flow:

1. **The tower.** A photoreal blue-hour image of a 20-floor seaside tower in Accra. Visitors hover over it or use the arrows to pick a floor. Each floor lights up and shows its unit type, price and status (available, reserved or sold).
2. **The flight.** Pressing "Enter floor N" plays a drone clip that flies in through the glass and lands on the terrace.
3. **Room by room.** Each clip ends on the exact frame where the next one starts: terrace and living room, then the master bedroom, then the ensuite. Hotspots and a room panel guide the visitor through.
4. **Booking.** "Book a viewing" is available at every step. It's a demo form and doesn't send anything yet.

All images and clips were made with Higgsfield (GPT Image 2.6 stills and Kling 3.0 clips that each start and end on a still). They load from Higgsfield's CDN, as listed in `MEDIA` in `index.html`.

## Lining up the floors
Open the page with `?setup` added to the URL, for example `index.html?setup`. Drag the sliders until the bands sit on the tower, then paste the printed `TOWER` line into `index.html`.

## Editing
Floors, prices and unit types are in `TYPES`, `SOLD` and `RESERVED`. Room names, descriptions and hotspots are in `ROOMS`.
