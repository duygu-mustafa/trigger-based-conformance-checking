import React, { useCallback, useEffect, useState } from 'react';
import { CHAPTERS } from './chapters';
import './story.css';

// Guided case-study story for the defense. The current chapter lives in the
// URL hash (#story/N) so it survives a reload and a trip to the timeline view.

export function readStoryHash() {
  const m = /^#story\/(\d+)/.exec(window.location.hash || '');
  return m ? Number(m[1]) : null;
}

const isTyping = (el) => el && (
  el.tagName === 'INPUT' || el.tagName === 'TEXTAREA' || el.tagName === 'SELECT' || el.isContentEditable
);

export default function StoryView({
  insights, drilldown, drilldownError, drillSel, onDrillChange,
  frequencyDetail, freqRule, onFreqRule, onOpenTimeline, onExplore,
}) {
  const [chapterId, setChapterId] = useState(() => readStoryHash() || 1);

  const visible = CHAPTERS;
  const pos = Math.max(0, visible.findIndex((c) => c.id === chapterId));
  const chapter = visible[pos] || CHAPTERS[0];

  const goTo = useCallback((id) => {
    setChapterId(id);
    window.history.replaceState(null, '', `#story/${id}`);
  }, []);

  useEffect(() => {
    if (!readStoryHash()) window.history.replaceState(null, '', `#story/${chapterId}`);
  }, [chapterId]);

  // Follow a chapter typed into the address bar
  useEffect(() => {
    const onHash = () => { const n = readStoryHash(); if (n) setChapterId(n); };
    window.addEventListener('hashchange', onHash);
    return () => window.removeEventListener('hashchange', onHash);
  }, []);

  const step = useCallback((delta) => {
    const next = visible[pos + delta];
    if (next) goTo(next.id);
  }, [visible, pos, goTo]);

  useEffect(() => {
    const onKey = (e) => {
      if (isTyping(e.target) || e.altKey || e.ctrlKey || e.metaKey) return;
      if (e.key === 'ArrowRight' || e.key === 'PageDown') { e.preventDefault(); step(1); }
      else if (e.key === 'ArrowLeft' || e.key === 'PageUp') { e.preventDefault(); step(-1); }
      else if (e.key === 'Home') { e.preventDefault(); goTo(visible[0].id); }
      else if (e.key === 'End') { e.preventDefault(); goTo(visible[visible.length - 1].id); }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [step, goTo, visible]);

  if (!insights) return null;
  const ctx = {
    insights, drilldown, drilldownError, drillSel, onDrillChange,
    frequencyDetail, freqRule, onFreqRule, onOpenTimeline, onExplore, goTo,
  };

  return (
    <div className="story">
      <nav className="story-rail" aria-label="Chapters">
        {visible.map((c, i) => (
          <button key={c.id} type="button"
                  className={`story-rail-item${c.id === chapter.id ? ' active' : ''}${i < pos ? ' done' : ''}${c.tag === 'optional' ? ' optional' : ''}`}
                  onClick={() => goTo(c.id)}
                  title={c.tag === 'optional' ? 'optional chapter' : undefined}>
            <span className="story-rail-label">{c.short}</span>
          </button>
        ))}
      </nav>

      <header className="story-head">
        <h2 className="story-claim">{chapter.claim(insights)}</h2>
      </header>

      <div className="story-body" key={chapter.id}>
        {chapter.render(ctx)}
      </div>

      <footer className="story-nav">
        <button type="button" className="story-btn" disabled={pos === 0} onClick={() => step(-1)}>
          ← {visible[pos - 1]?.short || 'Back'}
        </button>
        <span className="story-nav-pos">{pos + 1} / {visible.length}</span>
        <button type="button" className="story-btn primary" disabled={pos >= visible.length - 1} onClick={() => step(1)}>
          {visible[pos + 1]?.short || 'Next'} →
        </button>
      </footer>
    </div>
  );
}
