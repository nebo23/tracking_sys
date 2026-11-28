# Third-party notices for the design reference

These notices cover material embedded in `connect-icons.css` and referenced by the reference pages. Nothing here is a runtime dependency of the application yet; the frontend toolchain remains an open decision (Q-009).

## Lucide icons
`connect-icons.css` embeds 134 icons from `lucide-static` 1.69.0 as CSS masks.

```
ISC License

Copyright (c) 2026 Lucide Icons and Contributors

Permission to use, copy, modify, and/or distribute this software for any
purpose with or without fee is hereby granted, provided that the above
copyright notice and this permission notice appear in all copies.

THE SOFTWARE IS PROVIDED "AS IS" AND THE AUTHOR DISCLAIMS ALL WARRANTIES
WITH REGARD TO THIS SOFTWARE INCLUDING ALL IMPLIED WARRANTIES OF
MERCHANTABILITY AND FITNESS. IN NO EVENT SHALL THE AUTHOR BE LIABLE FOR
ANY SPECIAL, DIRECT, INDIRECT, OR CONSEQUENTIAL DAMAGES OR ANY DAMAGES
WHATSOEVER RESULTING FROM LOSS OF USE, DATA OR PROFITS, WHETHER IN AN
ACTION OF CONTRACT, NEGLIGENCE OR OTHER TORTIOUS ACTION, ARISING OUT OF
OR IN CONNECTION WITH THE USE OR PERFORMANCE OF THIS SOFTWARE.
```

Some Lucide icons derive from the Feather project and carry this notice:

```
The MIT License (MIT)

Copyright (c) 2013-present Cole Bemis

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

## Provider glyphs
`connect-icons.css` embeds 12 glyphs from Simple Icons 16.37.0, whose icon data is released under CC0 1.0 Universal. The names and marks of Instagram, YouTube, Meta, WhatsApp, X, TikTok, Facebook, Google, Google Ads, Cal.com, Stripe and HubSpot belong to their owners. The glyphs identify a connected service and imply no endorsement. Before release, check each provider's current brand guidelines; Google sign-in and YouTube have specific rules for how their marks appear.

The multicolor Google mark on the sign-in button in `preview/screens/sign-in.html` follows Google's published sign-in branding and must be re-checked against the current guidelines at implementation.

## Typefaces
The reference pages load these families from Google Fonts. No font file is stored in this repository.

| Family | Use | License |
|---|---|---|
| IBM Plex Sans, IBM Plex Sans Arabic, IBM Plex Mono | Interface text in both scripts, and code | SIL Open Font License 1.1 |
| Alexandria | Outlines of the Arabic wordmark only | SIL Open Font License 1.1 |
