# Cinematic stills — revision 2

Generated with the built-in `image_gen` tool. The final images are in
`public/stills/alex_{book,chatbot,video,relieved}.png` (media is gitignored).
These are photographic stills with a restrained animated camera push, not generated video.

## Book prompt

Use case: photorealistic-natural. Create a cinematic live-action advertising still,
widescreen 16:9. Alex is a real-looking 28-year-old man, olive skin, short wavy dark
brown hair, light stubble, wearing a navy overshirt over an ivory t-shirt. Medium
wide shot at a walnut desk in a lived-in contemporary apartment at blue hour, warm
desk lamp and cool window light. Alex on LEFT half leans over a very thick open
textbook, one hand resting naturally near pages, overwhelmed and tired. Real paper
edges, natural skin pores, believable anatomy, subtle film grain, premium 35mm lens
cinematography, photographic realism not illustration or 3D. Desk and laptop
extend to right; keep RIGHT third quiet dark defocused room for overlay titles.
Book and face fully visible, bottom 18 percent clear for subtitles. No floating
UI, no typography, no watermark, no collage. This is the first of four matching
movie frames.

## Other shots

Each call uses `alex_book.png` as its reference image and this prompt, substituting
the scene paragraph below for `{scene}`:

Use case: photorealistic-natural. Reference image is identity, wardrobe, apartment
and cinematography reference. Generate a NEW single widescreen 16:9 live-action
advertising movie still, same exact Alex face, navy overshirt, ivory t-shirt,
walnut desk, blue-hour apartment, warm lamp and cool window light. {scene}
Cinematic real photography, natural skin pores and hands, believable objects,
subtle grain. Keep right third quiet for overlay and bottom 18% clear for
subtitles. No floating UI, text, logos or collage.

- **Chatbot:** Alex now sits upright at the laptop, skeptical brow, reading an
  overwhelming answer, one hand on trackpad. The thick book is closed on desk.
  Medium shot, face on left, laptop on right.
- **Video:** Different tighter side angle of Alex impatiently watching a long
  lecture on laptop, chin resting in hand, screen light on his tired face. Thick
  book closed nearby. Face on left, laptop on right.
- **Relieved:** Alex sits relaxed with a subtle satisfied smile, having finally
  understood the answer on his laptop. Thick book now closed on desk, relaxed
  hands naturally resting. Wider shot, face on left, laptop on right.
