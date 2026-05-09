// Importing the registry plus each plugin module triggers self-registration.
// Order matters only for first-match resolution; here each plugin owns
// distinct sport_ids so order is cosmetic.
import "./basketball";
import "./cricket";
import "./mlb";
import "./nhl";

export { getPlugin, allSportIds } from "./registry";
