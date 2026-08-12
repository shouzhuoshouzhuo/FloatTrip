# 轻舟地图式行程详情设计 QA

## Source and implementation

- Source visual truth: `/var/folders/26/_71gxxn13jbbcryxmsml4nhc0000gn/T/codex-clipboard-747eeb09-4035-4f38-92f4-09b665ba8e4d.png`
- Implementation screenshot: `qa-map-detail-collapsed-screen.png`
- Expanded-state screenshot: `qa-map-detail-expanded-full.png`
- Pixel 10 screenshot: `qa-map-detail-pixel-full.png`
- Full-view comparison: `qa-map-comparison.png`
- Source pixels: 742 × 1550. App content was cropped and normalized to 393 × 852.
- Implementation CSS viewport: 393 × 852 at deviceScaleFactor 1. Implementation pixels: 393 × 852.
- Compared state: full-screen map, selected Day 1, collapsed/peek itinerary sheet, fixed action bar.

## Findings

No actionable P0, P1, or P2 mismatch remains.

- Typography: both screens use strong black date/place hierarchy, compact secondary text, and two practical UI weights. The implementation intentionally uses the established 轻舟 Chinese system stack instead of copying the competitor font.
- Spacing and rhythm: map occupies the device canvas, the bottom sheet begins near the mid-screen route context, date tabs remain horizontally scrollable, and the persistent actions clear the device safe area.
- Colors and tokens: pale cartography, orange numbered pins, sky-blue route/accent, white sheet, and black primary controls preserve the reference hierarchy while using 轻舟 tokens.
- Image quality: the new portrait map is a real 2048 × 3072 raster asset generated specifically for the full-screen slot. POI thumbnails remain real raster assets. No map or decorative asset is represented by CSS drawing or placeholder geometry.
- Copy/content: the reference's Nanjing content is correctly replaced with the prototype's Yunnan trip data while retaining the same information hierarchy.
- Interaction: the sheet supports tap and vertical-drag expansion logic; date switching, recommendations toggle, route optimization, edit/add, and continue-conversation remain interactive.

Focused comparison was performed through the combined full-view image because the map/sheet boundary, marker density, date rail, stop anatomy, and fixed action controls are all readable at 393 × 852. No separate focused crop was needed.

## Comparison history

### Iteration 1

- P1: the previous implementation used a conventional cover → route card → timeline page, so the map was a small secondary module rather than the primary spatial canvas.
- Fix: replaced the detail page with a full-screen generated portrait map and a persistent floating itinerary sheet.
- P1: itinerary details could not be pulled over the map.
- Fix: added compact and expanded sheet states with drag/tap control, spring motion, nested MobileScroll content, and a horizontal date Carousel.
- P2: core actions would have moved with the sheet and been absent from the compact state.
- Fix: promoted the action bar to a fixed sibling above both map and sheet; verified in compact and expanded states.
- P2: existing wide map asset would crop incorrectly in portrait.
- Fix: generated and installed `public/assets/app/dali-route-map-portrait.png` at 2048 × 3072.

Post-fix evidence: `qa-map-comparison.png`, `qa-map-detail-expanded-full.png`, and `qa-map-detail-pixel-full.png`.

## Verification

- `npm run check:runtime`: passed; 28 protected mobile-runtime files unchanged.
- `npm run build`: passed.
- `npm run test:runtime`: 11 passed, including the new full-map itinerary-sheet flow.
- In-app browser console: 0 warnings/errors on the map-detail screen.
- iPhone and Pixel 10 safe areas checked.

final result: passed
