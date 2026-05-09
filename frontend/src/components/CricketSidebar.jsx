"use client";

import BallByBallFeed from "./BallByBallFeed";
import CricketScorecard from "./CricketScorecard";
import CricketPreMatch from "./CricketPreMatch";

export default function CricketSidebar({ payload, status }) {
  if (!payload) return null;

  return (
    <>
      {status === "pre" && <CricketPreMatch game={payload} />}
      {payload.balls?.length > 0 && <BallByBallFeed balls={payload.balls} />}
      {payload.innings?.length > 0 && <CricketScorecard innings={payload.innings} />}
    </>
  );
}
