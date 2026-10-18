import { fireEvent, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { LinkedPlayer } from './LinkedPlayer';

const videos = [
  { key: 'a', label: 'Original', url: '/media/a.mp4', outcome: 'policy_failure' },
  { key: 'b', label: 'Minimal', url: '/media/b.mp4', outcome: 'policy_failure' },
  { key: 'c', label: 'Reference', url: null, outcome: 'success' },
];

function elements() {
  return Array.from(document.querySelectorAll('video'));
}

function stub(element: HTMLVideoElement, duration: number) {
  Object.defineProperty(element, 'duration', { configurable: true, value: duration });
  fireEvent.loadedMetadata(element);
}

describe('LinkedPlayer', () => {
  it('shows an empty state when no video exists', () => {
    render(<LinkedPlayer videos={[{ key: 'x', label: 'x', url: null, outcome: null }]} />);
    expect(screen.getByText('No videos were recorded for this case.')).toBeInTheDocument();
  });

  it('plays and pauses every video together, and restarts them', async () => {
    const user = userEvent.setup();
    const play = vi.spyOn(window.HTMLMediaElement.prototype, 'play');
    const pause = vi.spyOn(window.HTMLMediaElement.prototype, 'pause');
    render(<LinkedPlayer videos={videos} />);
    const [a, b] = elements() as [HTMLVideoElement, HTMLVideoElement];
    stub(a, 10);
    stub(b, 8);
    expect(screen.getByText('No video recorded')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: /play all/i }));
    expect(play).toHaveBeenCalledTimes(2);
    await user.click(screen.getByRole('button', { name: /pause/i }));
    expect(pause).toHaveBeenCalledTimes(2);
    a.currentTime = 4;
    b.currentTime = 3;
    await user.click(screen.getByRole('button', { name: /restart/i }));
    expect(a.currentTime).toBe(0);
    expect(b.currentTime).toBe(0);
    play.mockRestore();
    pause.mockRestore();
  });

  it('applies the speed to every video', async () => {
    const user = userEvent.setup();
    render(<LinkedPlayer videos={videos} />);
    await user.selectOptions(screen.getByLabelText('Speed'), '2');
    for (const element of elements()) expect(element.playbackRate).toBe(2);
  });

  it('moves every video with the shared timeline, clamped to each length', () => {
    render(<LinkedPlayer videos={videos} />);
    const [a, b] = elements() as [HTMLVideoElement, HTMLVideoElement];
    stub(a, 10);
    stub(b, 6);
    fireEvent.change(screen.getByLabelText('Position in the videos'), { target: { value: '8' } });
    expect(a.currentTime).toBe(8);
    expect(b.currentTime).toBe(6);
  });

  it('gives each video its own controls when "Keep in step" is off', async () => {
    const user = userEvent.setup();
    render(<LinkedPlayer videos={videos} />);
    expect(elements()[0]).not.toHaveAttribute('controls');
    await user.click(screen.getByRole('checkbox', { name: 'Keep in step' }));
    expect(elements()[0]).toHaveAttribute('controls');
    expect(screen.queryByLabelText('Position in the videos')).not.toBeInTheDocument();
  });

  it('lines the clips up at the earliest position when "Keep in step" is turned back on', async () => {
    const user = userEvent.setup();
    render(<LinkedPlayer videos={videos} />);
    const [a, b] = elements() as [HTMLVideoElement, HTMLVideoElement];
    stub(a, 10);
    stub(b, 10);
    const toggle = screen.getByRole('checkbox', { name: 'Keep in step' });
    await user.click(toggle); // off: each clip has its own controls
    a.currentTime = 7; // moved on its own
    b.currentTime = 2;
    await user.click(toggle); // back on
    expect(a.currentTime).toBe(2);
    expect(b.currentTime).toBe(2);
  });

  it('names each video and shows its outcome as a word', () => {
    render(<LinkedPlayer videos={videos} />);
    expect(screen.getByLabelText('Original')).toBeInTheDocument();
    expect(screen.getAllByText('failed')).toHaveLength(2);
    expect(screen.getByText('passed')).toBeInTheDocument();
  });
});
