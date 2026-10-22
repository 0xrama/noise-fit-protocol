# Official app watch face downloads

The official NoiseFit Android app obtains faces from an online catalog and downloads the selected face's binary resources. The XAPK includes the API clients and some model-specific dial templates, but does not contain a complete offline catalog of Twist faces.

## Catalog requests

NoiseFit 5.4.5's `WatchFaceRepositoryImpl` and coroutine classes identify these routes:

| Purpose | GET URL |
| --- | --- |
| Inbuilt face list | `https://app-eks.gonoise.com/watch_faces/in_built/list` |
| Category groups | `https://app-eks.gonoise.com/watch_faces/list_by_category` |
| Faces in a category | `https://app-eks.gonoise.com/watch_faces/v2/watchfaces_by_category/{category_id}` |
| New faces | `https://app-eks.gonoise.com/watch_faces/newly_added_list` |
| Popular faces | `https://app-eks.gonoise.com/watch_faces/top_downloaded_list` |

The network interceptor attaches the account access token using the **`access-token: Bearer …`** header. This differs from the usual `Authorization` header. It also attaches selected-device metadata: `device-id`, `device-type`, `device-no`, and `firmware-version`, along with app version and platform headers. Device metadata comes from `ColorFitDevice` and `WatchInfoGlobals`.

The cloud `device-id` is not established by reading equipment number 32005 or a Bluetooth identifier. Preserve that distinction when adding a catalog browser. A BLE binding token and the account's HTTP access token are also different credentials.

Live unauthenticated checks on 2026-10-17 returned HTTP **401 Unauthorized** for the inbuilt list, category groups, general face list, and v2 category-list endpoints. No account session was available on the Mac, so no authenticated face list or downloadable binary was obtained. The `vendor/list?fv=1.2.1` string found in the APK returned 404 when checked; it is not a verified working fallback.

## Download metadata

`WatchFace` distinguishes the catalog integer `id`, string `faceId`, target `deviceId`, preview `image_url`, binary `fileUrl`, and archive `zip_file` fields. A preview image is not a compiled face binary, and a cloud catalog ID is not automatically an installed watch-face ID.

The repository also exposes a download-info operation mapped by `NetworkService` to `GET /cloud_watch_faces/v3/dial_plate/info?id=…`. Its `WatchFaceDownloadResponse` contains preview information plus a `zip` object with `url` and `originalFileName`. That operation is another model-specific path; its presence does not prove it is the correct download route for Twist.

`DownloadService` streams files from URLs supplied by those responses. The selected binary then enters the model's preparation/upload pipeline documented in [Android watch protocol](android-protocol.md). Catalog browsing, downloading, compiling custom resources, and installing a face are separate steps.

## Current availability

Five installed faces were successfully listed on the test watch, and selecting an existing face worked. Additional official faces require a valid account session or files already downloaded by the official app. Such files still need the model/format check before installation. No face purchase, deletion, or upload was performed during the catalog investigation.

The bundled assets and reusable compiler primitives are described in [watch-face components](watchface-components.md), including the remaining model dependencies and why Facer faces cannot be imported directly.

Local source traces are under `.analysis/noisefit-5.4.5/targeted/`. HTTP status evidence is in `.analysis/watchface-catalog/public-endpoint-checks.json`. Account credentials and downloaded account-specific catalog responses should remain outside Git.
