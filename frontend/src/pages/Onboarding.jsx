import { useState, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import { markOnboardingComplete } from '../utils/onboarding';
import './Onboarding.css';

const SLIDES = [
  {
    id: 'welcome',
    variant: 'gradient',
    content: (
      <>
        <div className="onboarding-logo" aria-hidden>
          <span className="onboarding-logo-diamond">{'\u25C6'}</span>
          <span className="onboarding-logo-name">kashé</span>
        </div>
        <h1 className="onboarding-heading">Welcome to Kashé</h1>
        <p className="onboarding-subtext">
          Earn points for showing up to the studios you love.
        </p>
      </>
    ),
  },
  {
    id: 'challenges',
    variant: 'light',
    step: '01',
    heading: 'Join Challenges',
    subtext:
      'Complete classes at boutique studios and track your progress toward rewards.',
  },
  {
    id: 'points',
    variant: 'light',
    step: '02',
    heading: 'Earn Points',
    subtext:
      'Every class brings you closer to something real — Lululemon, SoulCycle, Pressed Juicery and more.',
  },
  {
    id: 'kai',
    variant: 'light',
    step: '03',
    heading: 'Meet Kai',
    subtext:
      'Your personal Kashé coach. Ask Kai to plan your week, check your pace, or just get motivated.',
  },
];

const SWIPE_THRESHOLD_PX = 50;

function Onboarding() {
  const navigate = useNavigate();
  const [activeIndex, setActiveIndex] = useState(0);
  const touchStartX = useRef(null);

  const finish = () => {
    markOnboardingComplete();
    navigate('/challenges');
  };

  const goNext = () => {
    if (activeIndex >= SLIDES.length - 1) {
      finish();
      return;
    }
    setActiveIndex((i) => i + 1);
  };

  const goTo = (index) => {
    if (index >= 0 && index < SLIDES.length) {
      setActiveIndex(index);
    }
  };

  const onTouchStart = (e) => {
    touchStartX.current = e.touches[0].clientX;
  };

  const onTouchEnd = (e) => {
    if (touchStartX.current == null) return;
    const delta = e.changedTouches[0].clientX - touchStartX.current;
    touchStartX.current = null;
    if (delta < -SWIPE_THRESHOLD_PX && activeIndex < SLIDES.length - 1) {
      setActiveIndex((i) => i + 1);
    } else if (delta > SWIPE_THRESHOLD_PX && activeIndex > 0) {
      setActiveIndex((i) => i - 1);
    }
  };

  const isLast = activeIndex === SLIDES.length - 1;

  return (
    <div
      className={`onboarding-overlay${activeIndex === 0 ? ' onboarding-overlay--welcome' : ''}`}
      role="dialog"
      aria-label="Welcome to Kashé"
    >
      {!isLast && (
        <button type="button" className="onboarding-skip" onClick={finish}>
          Skip
        </button>
      )}

      <div
        className="onboarding-viewport"
        onTouchStart={onTouchStart}
        onTouchEnd={onTouchEnd}
      >
        <div
          className="onboarding-track"
          style={{ transform: `translateX(-${activeIndex * 100}%)` }}
        >
          {SLIDES.map((slide) => (
            <section
              key={slide.id}
              className={`onboarding-slide onboarding-slide--${slide.variant}`}
              aria-hidden={SLIDES[activeIndex].id !== slide.id}
            >
              <div className="onboarding-slide-inner">
                {slide.variant === 'gradient' ? (
                  slide.content
                ) : (
                  <>
                    <div className="onboarding-step-icon" aria-hidden>
                      {slide.step}
                    </div>
                    <h1 className="onboarding-heading">{slide.heading}</h1>
                    <p className="onboarding-subtext">{slide.subtext}</p>
                  </>
                )}
              </div>
            </section>
          ))}
        </div>
      </div>

      <div className="onboarding-footer">
        <div className="onboarding-dots" role="tablist" aria-label="Onboarding progress">
          {SLIDES.map((slide, index) => (
            <button
              key={slide.id}
              type="button"
              role="tab"
              aria-selected={index === activeIndex}
              aria-label={`Slide ${index + 1} of ${SLIDES.length}`}
              className={`onboarding-dot ${index === activeIndex ? 'onboarding-dot--active' : ''}`}
              onClick={() => goTo(index)}
            />
          ))}
        </div>
        <p className="onboarding-counter" aria-live="polite">
          {activeIndex + 1} of {SLIDES.length}
        </p>
        <button type="button" className="onboarding-next" onClick={goNext}>
          {isLast ? "Let's go" : 'Next →'}
        </button>
      </div>
    </div>
  );
}

export default Onboarding;
