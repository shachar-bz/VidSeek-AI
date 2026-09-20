import {
  useEffect,
  useRef,
  useState,
  type FocusEvent,
  type TouchEvent
} from "react";

import architectureImage from "../../assets/auth/architecture.jpg";
import cookingImage from "../../assets/auth/cooking.jpg";
import laboratoryImage from "../../assets/auth/laboratory.jpg";
import orbitImage from "../../assets/auth/orbit.jpg";
import waterCycleImage from "../../assets/auth/water-cycle.jpg";

const SHOWCASE_ITEMS = [
  {
    image: waterCycleImage,
    alt: "A lecturer explaining the water cycle to a classroom",
    question: "What does the video say about evaporation?",
    elapsed: "02:14",
    duration: "08:42"
  },
  {
    image: cookingImage,
    alt: "A chef demonstrating a fresh pasta recipe",
    question: "When does the chef add the fresh basil?",
    elapsed: "04:08",
    duration: "12:31"
  },
  {
    image: laboratoryImage,
    alt: "A scientist demonstrating an experiment in a laboratory",
    question: "Why does the solution begin to glow?",
    elapsed: "01:36",
    duration: "06:18"
  },
  {
    image: orbitImage,
    alt: "An astronaut floating above the Earth",
    question: "How does orbit keep the astronaut in free fall?",
    elapsed: "03:52",
    duration: "10:05"
  },
  {
    image: architectureImage,
    alt: "An architect working on a sustainable building model",
    question: "Which materials reduce the building's footprint?",
    elapsed: "05:21",
    duration: "14:09"
  }
] as const;

const AUTO_ADVANCE_MS = 6_500;
const SWIPE_THRESHOLD_PX = 48;

function wrappedIndex(index: number): number {
  return (index + SHOWCASE_ITEMS.length) % SHOWCASE_ITEMS.length;
}

function showcaseItem(index: number) {
  return SHOWCASE_ITEMS[wrappedIndex(index)]!;
}

function useMediaQuery(query: string): boolean {
  const [matches, setMatches] = useState(() =>
    typeof window.matchMedia === "function" ? window.matchMedia(query).matches : false
  );

  useEffect(() => {
    if (typeof window.matchMedia !== "function") return;
    const mediaQuery = window.matchMedia(query);
    const updateMatch = () => setMatches(mediaQuery.matches);
    updateMatch();
    mediaQuery.addEventListener("change", updateMatch);
    return () => mediaQuery.removeEventListener("change", updateMatch);
  }, [query]);

  return matches;
}

export function AuthShowcaseCarousel() {
  const [activeIndex, setActiveIndex] = useState(0);
  const [transitionDirection, setTransitionDirection] = useState<"next" | "previous">("next");
  const [manualNavigationRevision, setManualNavigationRevision] = useState(0);
  const [isHovered, setIsHovered] = useState(false);
  const [hasFocusWithin, setHasFocusWithin] = useState(false);
  const [isDocumentHidden, setIsDocumentHidden] = useState(() => document.hidden);
  const touchStartX = useRef<number | null>(null);
  const prefersReducedMotion = useMediaQuery("(prefers-reduced-motion: reduce)");
  const isMobile = useMediaQuery("(max-width: 36rem)");
  const activeItem = showcaseItem(activeIndex);
  const previousItem = showcaseItem(activeIndex - 1);
  const nextItem = showcaseItem(activeIndex + 1);
  const transitionClass = `auth-carousel__motion--${transitionDirection}`;
  const autoplayPaused =
    prefersReducedMotion || isMobile || isHovered || hasFocusWithin || isDocumentHidden;

  useEffect(() => {
    const updateVisibility = () => setIsDocumentHidden(document.hidden);
    document.addEventListener("visibilitychange", updateVisibility);
    return () => document.removeEventListener("visibilitychange", updateVisibility);
  }, []);

  useEffect(() => {
    if (autoplayPaused) return;
    const timer = window.setTimeout(() => {
      setTransitionDirection("next");
      setActiveIndex((index) => wrappedIndex(index + 1));
    }, AUTO_ADVANCE_MS);
    return () => window.clearTimeout(timer);
  }, [activeIndex, autoplayPaused, manualNavigationRevision]);

  function navigateTo(index: number, direction: "next" | "previous") {
    setTransitionDirection(direction);
    setActiveIndex(wrappedIndex(index));
    setManualNavigationRevision((revision) => revision + 1);
  }

  function showPrevious() {
    navigateTo(activeIndex - 1, "previous");
  }

  function showNext() {
    navigateTo(activeIndex + 1, "next");
  }

  function handleBlur(event: FocusEvent<HTMLDivElement>) {
    if (!event.relatedTarget || !event.currentTarget.contains(event.relatedTarget as Node)) {
      setHasFocusWithin(false);
    }
  }

  function handleTouchStart(event: TouchEvent<HTMLDivElement>) {
    touchStartX.current = event.touches[0]?.clientX ?? null;
  }

  function handleTouchEnd(event: TouchEvent<HTMLDivElement>) {
    const endX = event.changedTouches[0]?.clientX;
    const startX = touchStartX.current;
    touchStartX.current = null;
    if (startX === null || endX === undefined) return;

    const distance = startX - endX;
    if (Math.abs(distance) < SWIPE_THRESHOLD_PX) return;
    if (distance > 0) showNext();
    else showPrevious();
  }

  return (
    <div
      className="auth-showcase"
      role="region"
      aria-label="VidSeek video search examples"
      onMouseEnter={() => setIsHovered(true)}
      onMouseLeave={() => setIsHovered(false)}
      onFocusCapture={() => setHasFocusWithin(true)}
      onBlurCapture={handleBlur}
      onTouchStart={handleTouchStart}
      onTouchEnd={handleTouchEnd}
      onTouchCancel={() => {
        touchStartX.current = null;
      }}
    >
      <div className="auth-carousel">
        <div
          key={`previous-${activeIndex}`}
          className={`auth-carousel__peek auth-carousel__peek--previous ${transitionClass}`}
          aria-hidden="true"
        >
          <img src={previousItem.image} alt="" />
        </div>

        <div key={`stage-${activeIndex}`} className={`auth-carousel__stage ${transitionClass}`}>
          <img
            className="auth-carousel__image"
            src={activeItem.image}
            alt={activeItem.alt}
          />
          <span className="auth-carousel__play" aria-hidden="true">
            <svg viewBox="0 0 24 24" focusable="false">
              <path d="m9 7 8 5-8 5V7Z" />
            </svg>
          </span>
          <div className="auth-carousel__controls" aria-hidden="true">
            <div className="auth-carousel__timeline">
              <span />
              <i />
            </div>
            <div className="auth-carousel__control-row">
              <strong>
                {activeItem.elapsed} / {activeItem.duration}
              </strong>
              <div className="auth-carousel__control-icons">
                <svg viewBox="0 0 24 24" focusable="false">
                  <path d="M5 9v6h4l5 4V5L9 9H5Zm11.5 3a4.5 4.5 0 0 0-2-3.74v7.48A4.5 4.5 0 0 0 16.5 12Z" />
                </svg>
                <svg viewBox="0 0 24 24" focusable="false">
                  <path d="M7 14H5v5h5v-2H7v-3Zm-2-4h2V7h3V5H5v5Zm12 7h-3v2h5v-5h-2v3Zm-3-12v2h3v3h2V5h-5Z" />
                </svg>
              </div>
            </div>
          </div>
        </div>

        <div
          key={`next-${activeIndex}`}
          className={`auth-carousel__peek auth-carousel__peek--next ${transitionClass}`}
          aria-hidden="true"
        >
          <img src={nextItem.image} alt="" />
        </div>

        <button
          className="auth-carousel__arrow auth-carousel__arrow--previous"
          type="button"
          aria-label="Previous example"
          onClick={showPrevious}
        >
          <svg viewBox="0 0 24 24" aria-hidden="true">
            <path d="m15 18-6-6 6-6" />
          </svg>
        </button>
        <button
          className="auth-carousel__arrow auth-carousel__arrow--next"
          type="button"
          aria-label="Next example"
          onClick={showNext}
        >
          <svg viewBox="0 0 24 24" aria-hidden="true">
            <path d="m9 18 6-6-6-6" />
          </svg>
        </button>
      </div>

      <div
        key={`question-${activeIndex}`}
        className={`auth-showcase__question ${transitionClass}`}
        aria-live="polite"
      >
        <svg viewBox="0 0 24 24" aria-hidden="true">
          <circle cx="11" cy="11" r="7" />
          <path d="m16 16 4 4" />
        </svg>
        <span>{activeItem.question}</span>
      </div>

      <div className="auth-showcase__dots" aria-label="Choose a video example">
        {SHOWCASE_ITEMS.map((item, index) => (
          <button
            key={item.question}
            type="button"
            className={
              index === activeIndex
                ? "auth-showcase__dot auth-showcase__dot--active"
                : "auth-showcase__dot"
            }
            aria-label={`Show example ${index + 1} of ${SHOWCASE_ITEMS.length}`}
            aria-current={index === activeIndex ? "true" : undefined}
            onClick={() =>
              navigateTo(index, index < activeIndex ? "previous" : "next")
            }
          />
        ))}
      </div>
    </div>
  );
}
