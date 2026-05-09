import LiveScoreBanner from "../components/LiveScoreBanner";
import BasketballSidebar from "../components/BasketballSidebar";
import { register } from "./registry";

register("basketball", {
  Banner: LiveScoreBanner,
  Sidebar: BasketballSidebar,
});
