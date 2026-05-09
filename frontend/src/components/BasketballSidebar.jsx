"use client";

import PlayByPlayFeed from "./PlayByPlayFeed";
import BoxScore from "./BoxScore";
import InjuryReport from "./InjuryReport";
import SeasonSeries from "./SeasonSeries";
import PreGameStats from "./PreGameStats";

export default function BasketballSidebar({ payload, status }) {
  if (!payload) return null;

  return (
    <>
      {status === "pre" && (payload.home_pregame || payload.away_pregame || payload.predictor) && (
        <PreGameStats
          home={payload.home}
          away={payload.away}
          homePregame={payload.home_pregame}
          awayPregame={payload.away_pregame}
          predictor={payload.predictor}
          gameTime={payload.game_time}
          venue={payload.venue}
          broadcast={payload.broadcast}
        />
      )}
      {payload.plays?.length > 0 && (
        <PlayByPlayFeed
          plays={payload.plays}
          homeTricode={payload.home.tricode}
          awayTricode={payload.away.tricode}
        />
      )}
      {payload.box_score && (
        <BoxScore
          boxScore={payload.box_score}
          homeTricode={payload.home.tricode}
          awayTricode={payload.away.tricode}
        />
      )}
      {payload.injuries?.length > 0 && (
        <InjuryReport
          injuries={payload.injuries}
          homeTricode={payload.home.tricode}
          awayTricode={payload.away.tricode}
        />
      )}
      {payload.season_series && (
        <SeasonSeries
          series={payload.season_series}
          homeTricode={payload.home.tricode}
          awayTricode={payload.away.tricode}
        />
      )}
    </>
  );
}
