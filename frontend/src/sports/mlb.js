import MLBScoreBanner from "../components/MLBScoreBanner";
import MLBMatchInfo from "../components/MLBMatchInfo";
import MLBSidebar from "../components/MLBSidebar";
import { register } from "./registry";

function MLBBanner({ payload, polymarketPrice }) {
  return <MLBScoreBanner game={payload} polymarketPrice={polymarketPrice} />;
}

function MLBHeader({ payload, status }) {
  if (status === "pre" && !payload?.probable_home && !payload?.probable_away) return null;
  return <MLBMatchInfo game={payload} />;
}

register("mlb", { Banner: MLBBanner, Header: MLBHeader, Sidebar: MLBSidebar });
