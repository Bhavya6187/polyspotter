import CricketScoreBanner from "../components/CricketScoreBanner";
import CricketMatchInfo from "../components/CricketMatchInfo";
import CricketSidebar from "../components/CricketSidebar";
import { register } from "./registry";

register("cricket", {
  Banner: CricketScoreBanner,
  Header: CricketMatchInfo,
  Sidebar: CricketSidebar,
});
