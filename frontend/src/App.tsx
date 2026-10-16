import { useEffect, useMemo, useRef, useState } from 'react';

type Track = {
  position: number;
  artist: string;
  track: string;
  preview_url: string | null;
};

const API = import.meta.env.VITE_API_URL ?? '';

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API}${path}`, init);
  const data = await response.json();
  if (!response.ok) throw new Error(data.error ?? 'An error occurred.');
  return data as T;
}

function App() {
  const [country, setCountry] = useState('global');
  const [countryInput, setCountryInput] = useState('global');
  const [tracks, setTracks] = useState<Track[]>([]);
  const [selected, setSelected] = useState<Track | null>(null);
  const [query, setQuery] = useState('');
  const [status, setStatus] = useState('Loading international playlist...');
  const [busy, setBusy] = useState(false);
  const [phase, setPhase] = useState('');
  const [progress, setProgress] = useState({ done: 0, total: 0 });
  const [view, setView] = useState<'top' | 'playlist' | 'history'>('top');
  const [savedTracks, setSavedTracks] = useState<Track[]>(() => {
    try {
      return JSON.parse(
        localStorage.getItem('muvo-playlist')
          ?? localStorage.getItem('melo-playlist')
          ?? '[]',
      ) as Track[];
    } catch { return []; }
  });
  const [history, setHistory] = useState<string[]>(() => {
    try { return JSON.parse(localStorage.getItem('melo-history') ?? '[]') as string[]; } catch { return []; }
  });
  const audio = useRef(new Audio());
  const [previewSeconds, setPreviewSeconds] = useState(0);
  const [previewLimit, setPreviewLimit] = useState(30);
  const [jobId, setJobId] = useState<string | null>(null);
  const [isPlaying, setIsPlaying] = useState(false);

  const visibleTracks = useMemo(
    () => (view === 'playlist' ? savedTracks : tracks).filter((item) =>
      `${item.artist} ${item.track}`.toLocaleLowerCase('ro').includes(query.toLocaleLowerCase('ro')),
    ),
    [tracks, savedTracks, query, view],
  );

  const activeTracks = view === 'playlist' ? savedTracks : tracks;
  const canDownload = view === 'playlist' && activeTracks.length > 0;

  function trackKey(track: Track) {
    return `${track.artist.trim().toLocaleLowerCase('ro')}|${track.track.trim().toLocaleLowerCase('ro')}`;
  }

  async function loadCountry(value = countryInput) {
    const normalized = value.trim().toLowerCase();

    if (!/^[a-z]{2,12}$/.test(normalized)) {
      setStatus('Use a code such as ro, de, us, or global.');
      return;
    }

    setBusy(true);
    setStatus(`Loading chart for ${normalized.toUpperCase()}...`);

    try {
      const data = await request<{ country: string; tracks: Track[] }>(
        `/api/country?country=${encodeURIComponent(normalized)}`,
      );

      setCountry(data.country);
      setCountryInput(data.country);
      setTracks(data.tracks);
      setSelected(null);
      setView('top');

      setHistory((current) => {
        const next = [
          `${data.country.toUpperCase()} · ${new Date().toLocaleString('ro-RO')}`,
          ...current,
        ].slice(0, 20);

        localStorage.setItem('melo-history', JSON.stringify(next));
        return next;
      });

      setStatus(`${data.tracks.length} clean tracks available.`);
    } catch (error) {
      setStatus(
        error instanceof Error
          ? error.message
          : 'Could not load the playlist.',
      );
    } finally {
      setBusy(false);
    }
  }

  async function cancelDownload() {
    if (!jobId) return;

    try {
      await request(
        `/api/download-cancel?job=${encodeURIComponent(jobId)}`,
        { method: 'PUT' },
      );

      setStatus('Stopping download...');
    } catch (error) {
      setStatus(
        error instanceof Error
          ? error.message
          : 'Could not stop the download.',
      );
    }
  }

 async function play(track: Track) {
  let previewUrl = track.preview_url;

  if (selected === track && !audio.current.paused) {
    audio.current.pause();
    setIsPlaying(false);
    return;
  }

  try {
    if (!previewUrl) {
      setStatus(`Loading preview for "${track.track}"...`);

      const data = await request<{ preview_url: string }>(
        `/api/preview?artist=${encodeURIComponent(track.artist)}&track=${encodeURIComponent(track.track)}`
      );

      previewUrl = data.preview_url;

      setTracks((current) =>
        current.map((item) =>
          trackKey(item) === trackKey(track)
            ? { ...item, preview_url: previewUrl }
            : item
        )
      );

      setSavedTracks((current) =>
        current.map((item) =>
          trackKey(item) === trackKey(track)
            ? { ...item, preview_url: previewUrl }
            : item
        )
      );
    }

    if (!previewUrl) {
      setStatus('Preview unavailable for this track.');
      return;
    }

    const fullPreviewUrl = `${API}${previewUrl}`;

    if (selected === track && audio.current.paused) {
      await audio.current.play();
      setIsPlaying(true);
      return;
    }

    setSelected(track);

    if (
      audio.current.src !==
      new URL(fullPreviewUrl, window.location.href).href
    ) {
      audio.current.src = fullPreviewUrl;
    }

    audio.current.currentTime = 0;
    setPreviewSeconds(0);
    setPreviewLimit(30);

    await audio.current.play();

    setIsPlaying(true);
    setStatus(`Playing preview: ${track.artist} - ${track.track}`);
  } catch (error) {
    setSelected(null);
    setIsPlaying(false);

    setStatus(
      error instanceof Error
        ? error.message
        : 'The preview could not be loaded.'
    );
  }
}

  function remove(track: Track) {
    if (selected === track) {
      audio.current.pause();
      setSelected(null);
      setIsPlaying(false);
    }

    if (view === 'playlist') {
      setSavedTracks((current) => {
        const next = current.filter((item) => item !== track);
        localStorage.setItem('muvo-playlist', JSON.stringify(next));
        return next;
      });
    } else {
      setTracks((current) =>
        current.filter((item) => item !== track)
      );
    }

    setStatus(`You removed "${track.track}".`);
  }

  function addToPlaylist(items: Track[]) {
    const additions = items.filter(
      (item, index) =>
        items.findIndex(
          (candidate) =>
            trackKey(candidate) === trackKey(item),
        ) === index,
    );

    const merged = [...savedTracks];
    let added = 0;
    let duplicates = 0;

    for (const item of additions) {
      if (
        merged.some(
          (saved) =>
            trackKey(saved) === trackKey(item),
        )
      ) {
        duplicates += 1;
        continue;
      }

      merged.push({
        ...item,
        position: merged.length + 1,
      });

      added += 1;
    }

    setSavedTracks(merged);
    localStorage.setItem(
      'muvo-playlist',
      JSON.stringify(merged),
    );

    if (items.length === 1 && duplicates === 1) {
      setStatus(
        `"${items[0].track}" is already in My Playlist.`,
      );
      return;
    }

    const details = [
      added ? `${added} added` : '',
      duplicates ? `${duplicates} already added` : '',
    ]
      .filter(Boolean)
      .join(' · ');

    setStatus(
      `${details || 'No new tracks'} · Playlist: ${merged.length} tracks.`,
    );
  }

  async function download() {
    if (!canDownload) {
      setStatus(
        'Add at least one track to My Playlist before downloading the archive.',
      );
      return;
    }

    setBusy(true);
    setPhase('download');
    setProgress({
      done: 0,
      total: activeTracks.length,
    });

    setStatus(
      'Preparing the archive. This process may take a few minutes...',
    );

    try {
      const data = await request<{ job: string }>(
        '/api/download-week?country=' +
          encodeURIComponent(country),
        {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
          },
          body: JSON.stringify({
            tracks: activeTracks.map(
              ({ artist, track }) => ({
                artist,
                track,
              }),
            ),
          }),
        },
      );

      setJobId(data.job);

      let finished = false;

      while (!finished) {
        await new Promise((resolve) =>
          window.setTimeout(resolve, 2000),
        );

        const statusData = await request<{
          status: string;
          phase?: string;
          done?: number;
          total?: number;
          downloaded?: number;
          error?: string;
        }>(
          `/api/download-status?job=${encodeURIComponent(data.job)}`,
        );

        if (statusData.status === 'error') {
          throw new Error(
            statusData.error ?? 'Download failed.',
          );
        }

        if (statusData.status === 'cancelled') {
          setStatus('The download was stopped.');
          finished = true;
          break;
        }

        if (statusData.phase) {
          setPhase(statusData.phase);
        }

        if (statusData.done !== undefined) {
          setProgress({
            done: statusData.done,
            total:
              statusData.total ??
              activeTracks.length,
          });
        }

        if (statusData.status === 'done') {
          finished = true;

          window.location.href =
            `${API}/api/download-file?job=${encodeURIComponent(data.job)}`;

          setStatus(
            `${statusData.downloaded ?? activeTracks.length} tracks are ready.`,
          );

          setPhase('done');

          setHistory((current) => {
            const next = [
              `ZIP ${country.toUpperCase()} · ${new Date().toLocaleString('ro-RO')}`,
              ...current,
            ].slice(0, 20);

            localStorage.setItem(
              'melo-history',
              JSON.stringify(next),
            );

            return next;
          });
        }
      }
    } catch (error) {
      setStatus(
        error instanceof Error
          ? error.message
          : 'Download failed.',
      );
    } finally {
      setBusy(false);
    }
  }

  useEffect(() => {
    const player = audio.current;

    const update = () => {
      const seconds = Math.min(
        player.currentTime,
        previewLimit,
      );

      setPreviewSeconds(seconds);

      if (player.currentTime >= previewLimit) {
        player.pause();
      }
    };

    const metadata = () =>
      setPreviewLimit(
        Math.min(player.duration || 30, 30),
      );

    const pause = () => setIsPlaying(false);
    const playEvent = () => setIsPlaying(true);
    const ended = () => setIsPlaying(false);

    player.addEventListener(
      'timeupdate',
      update,
    );
    player.addEventListener(
      'loadedmetadata',
      metadata,
    );
    player.addEventListener(
      'pause',
      pause,
    );
    player.addEventListener(
      'play',
      playEvent,
    );
    player.addEventListener(
      'ended',
      ended,
    );

    return () => {
      player.removeEventListener(
        'timeupdate',
        update,
      );
      player.removeEventListener(
        'loadedmetadata',
        metadata,
      );
      player.removeEventListener(
        'pause',
        pause,
      );
      player.removeEventListener(
        'play',
        playEvent,
      );
      player.removeEventListener(
        'ended',
        ended,
      );
    };
  }, [previewLimit]);

  useEffect(() => {
    void loadCountry('global');
  }, []);

  function openView(
    nextView: 'top' | 'playlist' | 'history',
  ) {
    setView(nextView);

    if (nextView === 'playlist') {
      if (!savedTracks.length) {
        setStatus(
          'My Playlist is empty. Save some tracks first.',
        );
      }
    }
  }

  return (
    <div className="app">
      <aside className="sidebar">
        <div className="logo">
          <span>●</span> MUVO
        </div>

        <p className="eyebrow">
          Main menu
        </p>

        <button
          className={`nav ${
            view === 'top' ? 'active' : ''
          }`}
          onClick={() => openView('top')}
        >
          ◈ Top 200 Clean
        </button>

        <button
          className={`nav ${
            view === 'playlist' ? 'active' : ''
          }`}
          onClick={() =>
            openView('playlist')
          }
        >
          ♫ My Playlist
        </button>

        <button
          className={`nav ${
            view === 'history' ? 'active' : ''
          }`}
          onClick={() =>
            openView('history')
          }
        >
          ◷ History
        </button>

        <div className="side-note">
          Previews are played locally when the track exists in your library.
        </div>
      </aside>

      <main className="main">
        <header className="topbar">
          <form
            onSubmit={(event) => {
              event.preventDefault();
              void loadCountry();
            }}
            className="search"
          >
            <span>⌕</span>

            <input
              value={countryInput}
              onChange={(event) =>
                setCountryInput(
                  event.target.value,
                )
              }
              placeholder="Search country or enter global"
            />

            <button disabled={busy}>
              Load country
            </button>
          </form>

          <button
            className="download top-download"
            onClick={() => void download()}
            disabled={busy || !canDownload}
          >
            Download ZIP
          </button>
        </header>

        <section className="hero">
          <div className="hero-card">
            <p className="eyebrow orange">
              Clean playlist
            </p>

            <h1>Weekly Top Chart</h1>

            <p className="muted">
              {country.toUpperCase()} ·{' '}
              {tracks.length} selected tracks
            </p>

            <div className="hero-actions">
              <button
                className="download"
                onClick={() =>
                  void download()
                }
                disabled={
                  busy || !canDownload
                }
              >
                Download playlist
              </button>

              <span className="muted">
                {view === 'playlist'
                  ? `${savedTracks.length} tracks · Single ZIP`
                  : 'Add tracks to My Playlist'}
              </span>
            </div>
          </div>

          <div className="now-playing">
            <p className="eyebrow">
              Active preview
            </p>

            <h2>
              {selected?.track ??
                'Choose a track from the list'}
            </h2>

            <p className="muted">
              {selected?.artist ??
                'Press play to listen to a short preview'}
            </p>

            <div className="preview-time">
              {previewSeconds.toFixed(0)} /{' '}
              {previewLimit.toFixed(0)} sec
            </div>

            <div className="wave">
              {'▁▃▅▂▆▃▇▂▅▃▆▁▃▅▂▇'
                .split('')
                .map((bar, index) => (
                  <i
                    key={index}
                    style={{
                      height: `${
                        20 +
                        (index % 5) * 8
                      }px`,
                    }}
                  />
                ))}
            </div>
          </div>
        </section>

        <section className="list-header">
          <div>
            <p className="eyebrow orange">
              Playlist
            </p>

            <h2>
              All tracks{' '}
              <small>
                {visibleTracks.length}
              </small>
            </h2>
          </div>

          <input
            className="filter"
            value={query}
            onChange={(event) =>
              setQuery(event.target.value)
            }
            placeholder="Filter by artist or track..."
          />
        </section>

        <div className="list-actions">
          <p className="status">
            {status}
          </p>

          {view !== 'playlist' && (
            <button
              className="save"
              onClick={() =>
                addToPlaylist(tracks)
              }
              disabled={!tracks.length}
            >
              Add Top 200 to playlist
            </button>
          )}
        </div>

        {busy && (
          <div className="download-progress">
            <div className="progress-label">
              <span>
                {phase === 'zip'
                  ? 'Creating ZIP archive'
                  : 'Downloading tracks'}
              </span>

              <b>
                {progress.done}/
                {progress.total}
              </b>

              <button
                className="cancel"
                onClick={() =>
                  void cancelDownload()
                }
                disabled={
                  phase === 'cancelling'
                }
              >
                {phase === 'cancelling'
                  ? 'Stopping...'
                  : 'Stop'}
              </button>
            </div>

            <div className="progress-track">
              <i
                style={{
                  width: `${
                    progress.total
                      ? (progress.done /
                          progress.total) *
                        100
                      : 0
                  }%`,
                }}
              />
            </div>
          </div>
        )}

        {view === 'history' ? (
          <section className="history">
            {history.length ? (
              history.map((item) => (
                <div
                  key={item}
                  className="history-item"
                >
                  ◷ {item}
                </div>
              ))
            ) : (
              <p className="muted">
                History is empty.
              </p>
            )}
          </section>
        ) : (
          <section className="tracks">
            {visibleTracks.map(
              (track) => (
                <article
                  className={`track ${
                    selected === track
                      ? 'playing'
                      : ''
                  }`}
                  key={`${track.artist}-${track.track}-${track.position}`}
                >
                  <span className="number">
                    {String(
                      track.position,
                    ).padStart(3, '0')}
                  </span>

                  <button
                    className="play"
                    onClick={() =>
                      play(track)
                    }
                    aria-label={`${
                      selected === track &&
                      isPlaying
                        ? 'Pause'
                        : 'Play'
                    } ${track.track}`}
                  >
                    {selected === track &&
                    isPlaying
                      ? 'Ⅱ'
                      : '▶'}
                  </button>

                  <div className="track-info">
                    <strong>
                      {track.track}
                    </strong>

                    <span>
                      {track.artist}
                    </span>
                  </div>

                  <span
                    className={
                      track.preview_url
                        ? 'clean'
                        : 'no-preview'
                    }
                  >
                    {track.preview_url
                      ? 'PREVIEW'
                      : 'NO PREVIEW'}
                  </span>

                  {view === 'playlist' ? (
                    <button
                      className="remove"
                      onClick={() =>
                        remove(track)
                      }
                      aria-label={`Remove ${track.track}`}
                    >
                      ×
                    </button>
                  ) : (
                    <button
                      className="add-track"
                      onClick={() =>
                        addToPlaylist([
                          track,
                        ])
                      }
                      aria-label={`Add ${track.track}`}
                    >
                      ＋
                    </button>
                  )}
                </article>
              ),
            )}
          </section>
        )}
      </main>
    </div>
  );
}

export default App;