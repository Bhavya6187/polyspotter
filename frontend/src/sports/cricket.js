import CricketScoreBanner from "../components/CricketScoreBanner";
import CricketMatchInfo from "../components/CricketMatchInfo";
import CricketSidebar from "../components/CricketSidebar";
import { register } from "./registry";

function CricketBanner({ payload, polymarketPrice }) {
  return <CricketScoreBanner game={payload} polymarketPrice={polymarketPrice} />;
}

function CricketHeader({ payload, status }) {
  // CricketMatchInfo no-ops when fields are empty, but it shouldn't render
  // at all in the "pre" state — matches today's cricket-page-client behavior.
  if (status === "pre") return null;
  return <CricketMatchInfo game={payload} />;
}

register("cricket", {
  Banner: CricketBanner,
  Header: CricketHeader,
  Sidebar: CricketSidebar,
});
