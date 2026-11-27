# Earth Now

The Earth as the naked eye would see it from space at this moment: a web app for the phone that also works with no internet.

**Open it:** [www.adrianorangel.org/earth-now](https://www.adrianorangel.org/earth-now/). On an iPhone, Share → Add to Home Screen makes it an app.

There are no labels, lines, titles or buttons. One finger turns the globe, two fingers move, zoom and twist it, and two fingers dragged straight down tilt the view toward the horizon once you are low enough. Double-tap to step closer; double-tap the Moon to go there.

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
```

No build step. Open `index.html` from any web server to run it.

## Changing it

When `index.html` or anything in `tex/` changes, raise the version in the first line of `sw.js` (`earth-now-v18` → `earth-now-v19`). Otherwise phones that already hold the app keep the old copy.

## Clouds

With no internet the app shows a stored cloud map, carried slowly by the winds: realistic, but not today's weather.

Online it fetches a current picture every three hours from [live-cloud-maps](https://github.com/matteason/live-cloud-maps) (contains modified EUMETSAT data). That picture is a satellite heat picture, not a map of cloud, so the app first takes off the coldness of the clear ground in each region and counts only what is colder as cloud. Two limits follow from the feed:

- Where the ground itself is colder than about −7 °C the picture is maxed out and cloud cannot be told from ground. There, and poleward of about 65°, the stored map is used. In northern winter that is most land north of 40°.
- Low cloud about as warm as the sea under it does not show in a heat picture and is left out.

The aurora's strength follows NOAA's planetary K index when it can be fetched; otherwise an ordinary quiet night is shown.

## Where the data comes from

- Earth by day, by month, at night, its heights and stored clouds: NASA Blue Marble and Black Marble.
- Moon heights and colour: NASA's Lunar Reconnaissance Orbiter (LOLA and LROC).
- Live clouds: live-cloud-maps by Matt Eason, from EUMETSAT data.
- Aurora activity: NOAA Space Weather Prediction Center.

## Limits

- Checked in a software renderer and tried on one iPhone; other phones and graphics chips may differ.
- The ground map is about 5 km per pixel, so up close it is softer than the eye would see, and city lights are blobs rather than streets.
- Lunar craters under about 2 km are generated, not the real ones.
