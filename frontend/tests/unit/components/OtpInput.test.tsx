import { screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { useState } from 'react';
import { describe, expect, it } from 'vitest';

import { OtpInput } from '@/components/OtpInput';

import { renderWithMessages } from '../support/app';

function Harness({ initial = '' }: { initial?: string }) {
  const [value, setValue] = useState(initial);
  return (
    <>
      <span id="code-label">Six-digit code</span>
      <OtpInput value={value} onChange={setValue} labelledBy="code-label" />
      <output>{value}</output>
    </>
  );
}

const cell = (position: number) => screen.getByLabelText(`Digit ${position} of 6`);
const code = () => screen.getByRole('status').textContent;

describe('the one-time code field', () => {
  it('names the group and every cell', () => {
    renderWithMessages(<Harness />);
    expect(screen.getByRole('group', { name: 'Six-digit code' })).toBeInTheDocument();
    expect(screen.getAllByRole('textbox')).toHaveLength(6);
    expect(cell(1)).toHaveAttribute('autocomplete', 'one-time-code');
    expect(cell(1)).toHaveAttribute('inputmode', 'numeric');
  });

  it('moves along as digits are typed', async () => {
    const user = userEvent.setup();
    renderWithMessages(<Harness />);
    await user.click(cell(1));
    await user.keyboard('123456');
    expect(code()).toBe('123456');
    expect(cell(6)).toHaveFocus();
    expect(cell(4)).toHaveValue('4');
  });

  it('takes digits only', async () => {
    const user = userEvent.setup();
    renderWithMessages(<Harness />);
    await user.click(cell(1));
    await user.keyboard('1a 2-3');
    expect(code()).toBe('123');
    expect(cell(4)).toHaveFocus();
  });

  it('spreads a pasted code over the cells', async () => {
    const user = userEvent.setup();
    renderWithMessages(<Harness />);
    await user.click(cell(1));
    await user.paste('654 321');
    expect(code()).toBe('654321');
    expect(cell(6)).toHaveValue('1');
  });

  it('goes back one cell with Backspace in an empty cell', async () => {
    const user = userEvent.setup();
    renderWithMessages(<Harness />);
    await user.click(cell(1));
    await user.keyboard('12{Backspace}');
    expect(code()).toBe('1');
    expect(cell(2)).toHaveFocus();
  });

  it('replaces the digit of a cell that is typed in again', async () => {
    const user = userEvent.setup();
    renderWithMessages(<Harness initial="123456" />);
    await user.click(cell(3));
    await user.keyboard('9');
    expect(code()).toBe('129456');
  });

  it('moves between cells with the arrow keys', async () => {
    const user = userEvent.setup();
    renderWithMessages(<Harness initial="123" />);
    await user.click(cell(2));
    await user.keyboard('{ArrowRight}');
    expect(cell(3)).toHaveFocus();
    await user.keyboard('{ArrowLeft}{ArrowLeft}');
    expect(cell(1)).toHaveFocus();
  });
});
