import SoccerScoreBanner from "../components/SoccerScoreBanner";
import SoccerMatchInfo from "../components/SoccerMatchInfo";
import SoccerSidebar from "../components/SoccerSidebar";
import { register } from "./registry";

function SoccerBanner({ payload, polymarketPrice }) {
  return <SoccerScoreBanner game={payload} polymarketPrice={polymarketPrice} />;
}

function SoccerHeader({ payload, status }) {
  if (status === "pre" && !payload?.competition_round && !payload?.venue) return null;
  return <SoccerMatchInfo game={payload} />;
}

register("soccer", { Banner: SoccerBanner, Header: SoccerHeader, Sidebar: SoccerSidebar });
