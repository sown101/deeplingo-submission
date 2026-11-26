import idle from "./assets/otter-idle.png";
import listen from "./assets/otter-listen.png";
import happy from "./assets/otter-happy.png";
import think from "./assets/otter-think.png";
import speak from "./assets/otter-speak.png";
import sleepy from "./assets/otter-sleepy.png";

const images = { idle, listen, happy, think, speak, sleepy };

export function Mascot({ state = "idle", className = "", alt = "" }: {
  state?: keyof typeof images; className?: string; alt?: string;
}) {
  return <img className={`dl-mascot-art ${className}`} src={images[state]} alt={alt} decoding="async" />;
}
