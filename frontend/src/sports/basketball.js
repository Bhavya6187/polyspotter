import LiveScoreBanner from "../components/LiveScoreBanner";
import BasketballSidebar from "../components/BasketballSidebar";
import { register } from "./registry";

function BasketballBanner({ payload, polymarketPrice }) {
  return <LiveScoreBanner game={payload} polymarketPrice={polymarketPrice} />;
}

register("basketball", {
  Banner: BasketballBanner,
  Sidebar: BasketballSidebar,
});
