// The one entry of the stylesheet. The design files stay in docs/design, their single source:
// the reference pages, the token audit and this application read the same files.
// Load order: tokens, icons, components, fonts, then the few rules only a running application needs.
import '@design/tokens/tokens.css';
import '@design/ui/connect-icons.css';
import '@design/ui/connect-ui.css';

// IBM Plex as local files (D7): no request leaves for a font service. Each file declares the
// character ranges it covers, so a browser fetches only the scripts a page actually shows.
import '@fontsource/ibm-plex-sans/400.css';
import '@fontsource/ibm-plex-sans/500.css';
import '@fontsource/ibm-plex-sans/600.css';
import '@fontsource/ibm-plex-sans/700.css';
import '@fontsource/ibm-plex-sans-arabic/400.css';
import '@fontsource/ibm-plex-sans-arabic/500.css';
import '@fontsource/ibm-plex-sans-arabic/600.css';
import '@fontsource/ibm-plex-sans-arabic/700.css';
import '@fontsource/ibm-plex-mono/400.css';
import '@fontsource/ibm-plex-mono/500.css';

import './app.css';
