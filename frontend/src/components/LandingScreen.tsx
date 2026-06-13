import { APP_VERSION } from "../version";

type Props = {
  onLaunch: () => void;
};

export function LandingScreen({ onLaunch }: Props) {
  return (
    <div className="landing">
      <main className="landing-main">
        <img
          className="landing-logo"
          src="/images/mainLogo1.png"
          alt="AcDec Flashcard Generator"
        />
        <button type="button" className="primary landing-launch" onClick={onLaunch}>
          Launch Tool
        </button>
      </main>
      <footer className="landing-footer">
        <span className="landing-version muted">v{APP_VERSION}</span>
        <img
          className="landing-personal"
          src="/images/personalLogo.png"
          alt=""
        />
      </footer>
    </div>
  );
}
