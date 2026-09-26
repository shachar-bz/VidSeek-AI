import { loadFont } from "@remotion/google-fonts/Inter";

const { fontFamily } = loadFont("normal", { weights: ["400", "500", "600", "700", "800"], subsets: ["latin"] });

// Colors come from the VidSeek website (frontend CSS tokens) so the ad matches the product.
export const colors = {
  canvas: "#f6f7fc",
  canvasDeep: "#eceefa",
  cobalt: "#5266eb",
  cobaltSoft: "#dfe3fd",
  ink: "#171721",
  inkMuted: "#5d5d6c",
  mistBorder: "#e2e3ed",
  white: "#ffffff",
  warning: "#d9534f",
};

export const fonts = { sans: fontFamily };

export const shadows = {
  floatingScreen: "0 40px 90px rgba(30, 36, 90, 0.22), 0 12px 30px rgba(30, 36, 90, 0.12)",
  card: "0 24px 60px rgba(30, 36, 90, 0.18), 0 6px 18px rgba(30, 36, 90, 0.10)",
};
