import { Link } from "react-router-dom";
import { Mascot } from "../../design/Mascot";
import { I18nProvider, T } from "../../i18n/i18n";
import "./landing.css";

export function LandingScreen() {
  return <I18nProvider language="vi"><Landing /></I18nProvider>;
}

function Landing() {
  return <div className="landing-page">
    <header className="landing-nav">
      <Link to="/" className="landing-brand"><Mascot className="dl-brand-mascot" />DeepLingo</Link>
      <nav aria-label="DeepLingo"><a href="#how"><T>How it works</T></a><a href="#tata">Tata</a></nav>
      <Link className="dl-btn dl-btn--secondary" to="/signin"><T>Sign in</T></Link>
    </header>
    <main className="landing-content">
      <section className="landing-hero">
        <div className="landing-hero-copy">
          <span className="landing-eyebrow"><T>Real videos. Real conversations.</T></span>
          <h1><T>Learn from real videos, then talk with Tata.</T></h1>
          <p><T>Watch what you love. Save the words that matter. Use them in a conversation with your learning companion.</T></p>
          <div className="landing-actions"><Link className="dl-btn dl-btn--primary" to="/signin?mode=signup"><T>Create your account</T></Link><Link className="dl-btn dl-btn--secondary" to="/signin"><T>I already have an account</T></Link></div>
          <div className="landing-languages"><span>English</span><span>中文</span><span><T>Vietnamese explanations</T></span></div>
        </div>
        <div className="landing-hero-art">
          <div className="landing-orbit" aria-hidden="true" />
          <Mascot state="happy" className="landing-mascot" />
          <div className="landing-speech"><span className="landing-status-dot" /><T>What would you like to talk about?</T></div>
        </div>
      </section>
      <section className="landing-section" id="how" aria-labelledby="landing-how-title">
        <div className="landing-section-heading"><span className="landing-eyebrow">DeepLingo</span><h2 id="landing-how-title"><T>One learning loop. Three steps.</T></h2></div>
        <ol className="landing-steps">
          <li className="card"><span className="landing-step-number">01</span><h3><T>Watch something you love</T></h3><p><T>Bring a YouTube video and follow its transcript. Every word starts with a real context.</T></p></li>
          <li className="card"><span className="landing-step-number">02</span><h3><T>Keep words in your notebook</T></h3><p><T>Save useful words by topic. Familiarize yourself with flashcards and review when they are due.</T></p></li>
          <li className="card"><span className="landing-step-number">03</span><h3><T>Make the words your own</T></h3><p><T>Talk with Tata, get help when you need it, and see evidence of the words you use.</T></p></li>
        </ol>
      </section>
      <section className="card landing-tata" id="tata" aria-labelledby="landing-tata-title">
        <Mascot state="listen" />
        <div><span className="landing-eyebrow"><T>Your learning companion</T></span><h2 id="landing-tata-title"><T>Tata is by your side</T></h2><p><T>Ask about the part you are watching, or start a conversation about a topic you care about. Speak at your pace with captions and hints.</T></p><Link className="dl-btn dl-btn--secondary" to="/signin?mode=signup"><T>Meet Tata</T></Link></div>
      </section>
      <section className="card landing-privacy" aria-labelledby="landing-privacy-title">
        <span className="landing-privacy-symbol" aria-hidden="true">✓</span><div><h2 id="landing-privacy-title"><T>Your voice stays yours</T></h2><p><T>Audio is not stored. Voice processing requires your permission, which you can withdraw in Profile.</T></p><Link to="/privacy"><T>Privacy notice</T></Link></div>
      </section>
      <section className="landing-section landing-final" aria-labelledby="landing-final-title">
        <Mascot state="happy" /><h2 id="landing-final-title"><T>Start with a video you love</T></h2><p><T>One video. A few useful words. Your next conversation.</T></p><Link className="dl-btn dl-btn--primary" to="/signin?mode=signup"><T>Create your account</T></Link>
      </section>
    </main>
    <footer className="landing-footer"><span>DeepLingo</span><Link to="/privacy"><T>Privacy</T></Link><Link to="/signin"><T>Sign in</T></Link></footer>
    <div className="landing-mobile-cta"><Link className="dl-btn dl-btn--primary" to="/signin?mode=signup"><T>Create your account</T></Link></div>
  </div>;
}
