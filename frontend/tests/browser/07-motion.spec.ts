import { expect, test, type Page } from '@playwright/test';

/** What each traveller of the picture is doing: its animation and where it is on its track. */
const travellers = (page: Page) =>
  page.locator('.c-pull__mover').evaluateAll((elements) =>
    elements.map((element) => {
      const style = getComputedStyle(element);
      return { name: style.animationName, state: style.animationPlayState, place: style.offsetDistance };
    }),
  );

test('the picture moves, and a person can stop it', async ({ page }) => {
  await page.goto('/sign-in');
  await expect(page.getByRole('img', { name: /A magnet pulls people toward it/ })).toBeVisible();

  const moving = await travellers(page);
  expect(moving).toHaveLength(9);
  expect(new Set(moving.map((traveller) => traveller.name))).toEqual(new Set(['c-pull-travel']));
  expect(new Set(moving.map((traveller) => traveller.state))).toEqual(new Set(['running']));

  await page.getByRole('checkbox', { name: 'Pause animation' }).check();
  expect(new Set((await travellers(page)).map((traveller) => traveller.state))).toEqual(new Set(['paused']));

  await page.getByRole('checkbox', { name: 'Pause animation' }).uncheck();
  expect(new Set((await travellers(page)).map((traveller) => traveller.state))).toEqual(new Set(['running']));
});

test.describe('for a person who asked their device for less motion', () => {
  test.use({ contextOptions: { reducedMotion: 'reduce' } });

  test('the picture rests, with every traveller at a place of its own', async ({ page }) => {
    await page.goto('/sign-in');
    await expect(page.getByRole('img', { name: /A magnet pulls people toward it/ })).toBeVisible();

    const resting = await travellers(page);
    expect(new Set(resting.map((traveller) => traveller.name))).toEqual(new Set(['none']));
    // Three tracks with three places each, as the reference styles set them.
    expect(resting.map((traveller) => traveller.place)).toEqual(['12%', '44%', '78%', '20%', '46%', '70%', '12%', '44%', '78%']);
    // Nothing moves, so there is nothing to pause.
    await expect(page.locator('.l-auth__motion')).toBeHidden();
  });
});
