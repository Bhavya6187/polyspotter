import NHLScoreBanner from "../components/NHLScoreBanner";
import NHLMatchInfo from "../components/NHLMatchInfo";
import NHLSidebar from "../components/NHLSidebar";
import { register } from "./registry";

function NHLBanner({ payload, polymarketPrice }) {
  return <NHLScoreBanner game={payload} polymarketPrice={polymarketPrice} />;
}

function NHLHeader({ payload, status }) {
  if (status === "pre") return null;
  return <NHLMatchInfo game={payload} />;
}

register("nhl", { Banner: NHLBanner, Header: NHLHeader, Sidebar: NHLSidebar });
