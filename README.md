# Earth Now

The Earth as the naked eye would see it from space at this moment: a web app for the phone that also works with no internet.

**Open it:** [www.adrianorangel.org/earth-now](https://www.adrianorangel.org/earth-now/). On an iPhone, Share → Add to Home Screen makes it an app.

There are no labels, lines, titles or buttons. One finger turns the globe, two fingers move, zoom and twist it, and two fingers dragged down together tilt the view toward the horizon once the planet more than fills the screen. Double-tap to step closer; double-tap the Moon to go there.

## What it shows

- The Sun, Moon, stars and planets where they are right now, and the day and night sides that follow from them.
- Brightness and colour as a person with 20/20 vision would see them, not as a camera would: the eye adapts to what it is looking at, loses colour and sharpness in the dark, and is dazzled by the Sun. Stars only appear when nothing bright is in view.
- The ground at true scale (mountains are not exaggerated), the atmosphere, clouds with real thickness, city lights, lightning, the aurora, sun glint on the sea.
- The Moon with its real relief, lit by the actual Sun, and the Earth in its sky.

## Files

```
index.html     The whole app: one page, everything it draws
sw.js          Keeps it working with no internet
manifest.json  Lets a phone add it to the home screen
icon.png       The home-screen icon
tex/           Maps of the Earth and Moon, the Milky Way, and the star list
tools/clouds.py               Builds the hourly cloud map
.github/workflows/clouds.yml  Runs it every hour on GitHub
```

No build step. Open `index.html` from any web server to run it.

## Changing it

When `index.html` or anything in `tex/` changes, raise the version in the first line of `sw.js` (`earth-now-v23` → `earth-now-v24`). Otherwise phones that already hold the app keep the old copy.

## Clouds

Online, the app shows this hour's clouds. A job in this repository builds the map every hour (`tools/clouds.py`, run by `.github/workflows/clouds.yml`) and puts it on the `live` branch, where the app picks it up. The map is about an hour old when it appears. The job reads two public NOAA sources:

- **The hourly mosaic of the weather satellites** (GMGSI: GOES-West, GOES-East, two Meteosats and Himawari). In daylight, cloud is whatever is brighter in visible light than that place's clear-sky look, which is the darkest it has been at the same hour over the past week. At night, cloud is whatever is colder in infrared than the week's warmest reading.
- **How high the cloud tops are**, from how much colder they are than the ground in the same infrared pictures (about 6.5 °C for every kilometre). Thin cloud lets the warm ground shine through and reads lower than it is; in daylight the visible picture says how thin it is (dim means thin), and the ground's share of the reading is taken out. The app draws each cloud at that height.
- **The GFS weather model**, for what the satellites cannot give: cloud poleward of about 60 to 65°, low cloud at night (it is as warm as the ground, so infrared does not see it), the ground temperature (so that cold air behind a front is not read as cloud), and where snow and ice lie.

Limits:

- The night side is less exact than the day side. A night cloud's brightness is the average for cloud that cold, and low cloud at night and all cloud near the poles are the model's forecast, not an observation.
- Over snow and ice, cloud is hard to tell from the ground and is underestimated.
- A place that has been cloudy at the same hour all week has no clear-sky look to compare with, so thin cloud there can be missed.
- The map says how much cloud each spot of about 10 km holds and how high its top is, not the shape of each cloud. Those two measurements tell the families of cloud apart, and closer than 10 km the app draws each family its own way, blending smoothly between them:
  - thin and high (cirrus): a see-through veil drawn out into streaks;
  - low and not full (cumulus, broken stratocumulus): separate ragged clumps that cover exactly the measured share of the spot, lit on the side facing the sun;
  - low and full (stratus, fog): a smooth, even sheet;
  - thick and high (storms, fronts): a solid white sheet with a bulging top;
  - in between (middle cloud): a continuous, gently uneven sheet.

  Which family is where is measured. The single clumps and streaks are not the real ones, and cirrus streaks always run roughly east-west.
- Poleward of about 70° low cloud is drawn as a thin even sheet, not as clumps: heaped cloud needs a surface that warms the air, and there is no measurement of its texture there (the cloud comes from the weather model).
- Cloud heights are measured from the ground up, so the app adds the height of the ground below (smoothed over about 150 km). Cloud over Antarctica's ice or over Tibet sits above the surface, not inside it.
- Only one layer is known at each spot. Thin high cloud above low cloud is filed at a height between the two.
- Without this project's map (the stand-in picture or the stored map) there are no measured heights: only the brightest cloud is drawn as deep, the rest as low, and there is no cirrus.
- Seen from the side, cloud is a lit, lumpy sheet at the right height, not a true volume: towers do not stand up as separate shapes.
- At night there is no visible picture to say how thin a cloud is, so thin high cloud is still placed too low there and drawn as low cloud.
- Where two satellites' views meet (near 106° W, 38° W, 23° E, 93° E and 178° W) a faint straight step can show, mostly at a low Sun.

If that map is unreachable or more than 6 hours old, the app falls back to a 3-hourly picture from [live-cloud-maps](https://github.com/matteason/live-cloud-maps) (contains modified EUMETSAT data). That one is a heat picture, not a map of cloud, and cannot tell cloud from ground colder than about −7 °C, so it is only a stand-in. With no internet the app keeps showing the last map it received for 36 hours, then a stored cloud map carried slowly by the winds: realistic, but not today's weather.

To stop the job: Actions tab → clouds → ⋯ → Disable workflow.

The aurora's strength follows NOAA's planetary K index when it can be fetched; otherwise an ordinary quiet night is shown.

## Where the data comes from

- Earth by day, by month, at night, its heights and stored clouds: NASA Blue Marble and Black Marble.
- Moon heights and colour: NASA's Lunar Reconnaissance Orbiter (LOLA and LROC).
- Live clouds: made here from NOAA's GMGSI satellite mosaic and GFS model (NOAA Open Data Dissemination). The data is changed in the making and this project is not endorsed by NOAA. Stand-in: live-cloud-maps by Matt Eason, from EUMETSAT data.
- Aurora activity: NOAA Space Weather Prediction Center.

## Limits

- Checked in a software renderer and tried on one iPhone; other phones and graphics chips may differ.
- The ground map is about 5 km per pixel, so up close it is softer than the eye would see, and city lights are blobs rather than streets.
- Lunar craters under about 2 km are generated, not the real ones.
