import { useCallback, useEffect, useId, useRef, useState } from 'react';
import { Icon } from './Icon';
import { isFail, isPass, outcomeWord } from './Outcomes';

export interface PlayerVideo {
  key: string;
  label: string;
  url: string | null;
  outcome: string | null;
}

const SPEEDS = [0.25, 0.5, 1, 2];

function mmss(seconds: number): string {
  const total = Math.max(0, Math.floor(seconds));
  return `${Math.floor(total / 60)}:${String(total % 60).padStart(2, '0')}`;
}

/**
 * Several videos behind one set of controls: play all, pause, restart, speed and a shared timeline.
 * With "Keep in step" off, each video shows its own browser controls instead.
 */
export function LinkedPlayer({ videos, title }: { videos: PlayerVideo[]; title?: string }) {
  const refs = useRef<(HTMLVideoElement | null)[]>([]);
  const [playing, setPlaying] = useState(false);
  const [speed, setSpeed] = useState(1);
  const [sync, setSync] = useState(true);
  const [position, setPosition] = useState(0);
  const [durations, setDurations] = useState<number[]>([]);
  const speedId = useId();
  const scrubId = useId();

  const playable = videos.filter((video) => video.url !== null);
  const longest = Math.max(0, ...durations.filter((d) => Number.isFinite(d)));
  const leadIndex = durations.length ? durations.indexOf(Math.max(...durations.map((d) => (Number.isFinite(d) ? d : 0)))) : 0;

  const each = useCallback((fn: (video: HTMLVideoElement) => void) => {
    refs.current.forEach((video) => {
      if (video) fn(video);
    });
  }, []);

  useEffect(() => {
    each((video) => {
      video.playbackRate = speed;
    });
  }, [speed, each, videos]);

  if (playable.length === 0) {
    return <p className="empty">No videos were recorded for this case.</p>;
  }

  const playAll = () => {
    const finished = refs.current.every((video) => !video || video.ended || (Number.isFinite(video.duration) && video.currentTime >= video.duration));
    each((video) => {
      if (finished) video.currentTime = 0;
      video.playbackRate = speed;
      void Promise.resolve(video.play()).catch(() => undefined);
    });
    setPlaying(true);
  };
  const pauseAll = () => {
    each((video) => video.pause());
    setPlaying(false);
  };
  const restart = () => {
    each((video) => {
      video.currentTime = 0;
      if (playing) void Promise.resolve(video.play()).catch(() => undefined);
    });
    setPosition(0);
  };
  const scrub = (value: number) => {
    each((video) => {
      const limit = Number.isFinite(video.duration) ? video.duration : value;
      video.currentTime = Math.min(value, limit);
    });
    setPosition(value);
  };

  return (
    <div className="player" role="group" aria-label={title ?? 'Linked videos'}>
      <div className="player__videos" data-count={videos.length}>
        {videos.map((video, index) => (
          <figure className="player__item" key={video.key}>
            {video.url ? (
              <video
                ref={(element) => {
                  refs.current[index] = element;
                }}
                src={video.url}
                muted
                playsInline
                preload="metadata"
                controls={!sync}
                aria-label={video.label}
                onLoadedMetadata={(event) => {
                  const element = event.currentTarget;
                  element.playbackRate = speed;
                  setDurations((previous) => {
                    const next = [...previous];
                    next[index] = element.duration;
                    return next;
                  });
                }}
                onTimeUpdate={(event) => {
                  if (index === leadIndex) setPosition(event.currentTarget.currentTime);
                }}
                onEnded={() => {
                  const allDone = refs.current.every((v) => !v || v.ended);
                  if (allDone) setPlaying(false);
                }}
              />
            ) : (
              <div className="player__none">No video recorded</div>
            )}
            <figcaption>
              <span className="player__label">{video.label}</span>
              {video.outcome && (
                <span className="player__outcome">
                  <Icon name={isFail(video.outcome) ? 'close' : isPass(video.outcome) ? 'tick' : 'minus'} />
                  {outcomeWord(video.outcome)}
                </span>
              )}
            </figcaption>
          </figure>
        ))}
      </div>
      <div className="player__controls">
        {playing ? (
          <button type="button" className="btn btn--small" onClick={pauseAll}>
            <Icon name="pause" /> Pause
          </button>
        ) : (
          <button type="button" className="btn btn--small" onClick={playAll}>
            <Icon name="play" /> Play all
          </button>
        )}
        <button type="button" className="btn btn--secondary btn--small" onClick={restart}>
          <Icon name="restart" /> Restart
        </button>
        <label className="player__speed" htmlFor={speedId}>
          Speed
          <select id={speedId} value={speed} onChange={(event) => setSpeed(Number(event.target.value))}>
            {SPEEDS.map((value) => (
              <option key={value} value={value}>
                {value}x
              </option>
            ))}
          </select>
        </label>
        <label className="check player__sync">
          <input type="checkbox" checked={sync} onChange={(event) => setSync(event.target.checked)} />
          Keep in step
        </label>
        {sync && (
          <div className="player__scrub">
            <label htmlFor={scrubId} className="sr-only">
              Position in the videos
            </label>
            <input
              id={scrubId}
              type="range"
              min={0}
              max={longest || 1}
              step={0.05}
              value={Math.min(position, longest || 1)}
              onChange={(event) => scrub(Number(event.target.value))}
              aria-valuetext={`${mmss(position)} of ${mmss(longest)}`}
            />
            <span className="player__time mono" aria-hidden="true">
              {mmss(position)} / {mmss(longest)}
            </span>
          </div>
        )}
      </div>
    </div>
  );
}
