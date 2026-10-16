// The LIBERO benchmark's task instructions, so the form can show what each task asks for.
// Static on purpose: the control panel must not need the simulator to render a form. Keep in step with
// the benchmark; the server and the run itself are the authority on which tasks exist.
export const SUITES = ['libero_object', 'libero_spatial', 'libero_goal', 'libero_10'] as const;
export type Suite = (typeof SUITES)[number];

export const SUITE_LABEL: Record<Suite, string> = {
  libero_object: 'LIBERO-Object',
  libero_spatial: 'LIBERO-Spatial',
  libero_goal: 'LIBERO-Goal',
  libero_10: 'LIBERO-10',
};

const OBJECTS = [
  'alphabet soup',
  'cream cheese',
  'salad dressing',
  'bbq sauce',
  'ketchup',
  'tomato sauce',
  'butter',
  'milk',
  'chocolate pudding',
  'orange juice',
];

export const TASKS: Record<Suite, string[]> = {
  libero_object: OBJECTS.map((item) => `pick up the ${item} and place it in the basket`),
  libero_spatial: [
    'pick up the black bowl between the plate and the ramekin and place it on the plate',
    'pick up the black bowl next to the ramekin and place it on the plate',
    'pick up the black bowl from table center and place it on the plate',
    'pick up the black bowl on the cookie box and place it on the plate',
    'pick up the black bowl in the top drawer of the wooden cabinet and place it on the plate',
    'pick up the black bowl on the ramekin and place it on the plate',
    'pick up the black bowl next to the cookie box and place it on the plate',
    'pick up the black bowl on the stove and place it on the plate',
    'pick up the black bowl next to the plate and place it on the plate',
    'pick up the black bowl on the wooden cabinet and place it on the plate',
  ],
  libero_goal: [
    'open the middle drawer of the cabinet',
    'put the bowl on the stove',
    'put the wine bottle on top of the cabinet',
    'open the top drawer and put the bowl inside',
    'put the bowl on top of the cabinet',
    'push the plate to the front of the stove',
    'put the cream cheese in the bowl',
    'turn on the stove',
    'put the bowl on the plate',
    'put the wine bottle on the rack',
  ],
  libero_10: [
    'put both the alphabet soup and the tomato sauce in the basket',
    'put both the cream cheese box and the butter in the basket',
    'turn on the stove and put the moka pot on it',
    'put the black bowl in the bottom drawer of the cabinet and close it',
    'put the white mug on the left plate and put the yellow and white mug on the right plate',
    'pick up the book and place it in the back compartment of the caddy',
    'put the white mug on the plate and put the chocolate pudding to the right of the plate',
    'put both the alphabet soup and the cream cheese box in the basket',
    'put both moka pots on the stove',
    'put the yellow and white mug in the microwave and close it',
  ],
};

export function taskInstruction(suite: string, task: number): string | null {
  const list = (TASKS as Record<string, string[] | undefined>)[suite];
  return list?.[task] ?? null;
}

/** Image and scene disturbance families an audit can search (docs/setup/diagnose.md, configs/specs/audit.yaml). */
export const AUDIT_FAMILIES: { key: string; label: string; group: 'image' | 'scene' }[] = [
  { key: 'blur', label: 'Blur', group: 'image' },
  { key: 'noise', label: 'Noise', group: 'image' },
  { key: 'darken', label: 'Darken', group: 'image' },
  { key: 'contrast', label: 'Contrast', group: 'image' },
  { key: 'jpeg', label: 'JPEG compression', group: 'image' },
  { key: 'colour_cast', label: 'Colour cast', group: 'image' },
  { key: 'motion_blur', label: 'Motion blur', group: 'image' },
  { key: 'dead_pixels', label: 'Dead pixels', group: 'image' },
  { key: 'viewpoint', label: 'Camera viewpoint', group: 'scene' },
  { key: 'lighting', label: 'Lighting', group: 'scene' },
];
