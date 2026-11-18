/** Source files and the places in them. */

class File extends @file {
  string getAbsolutePath() { files(this, result) }

  string toString() { result = this.getAbsolutePath() }
}

class Location extends @location_default {
  File getFile() { locations_default(this, result, _, _, _, _) }

  int getStartLine() { locations_default(this, _, result, _, _, _) }

  int getStartColumn() { locations_default(this, _, _, result, _, _) }

  int getEndLine() { locations_default(this, _, _, _, result, _) }

  int getEndColumn() { locations_default(this, _, _, _, _, result) }

  string toString() { result = "line " + this.getStartLine() }

  predicate hasLocationInfo(string fp, int sl, int sc, int el, int ec) {
    fp = this.getFile().getAbsolutePath() and
    sl = this.getStartLine() and
    sc = this.getStartColumn() and
    el = this.getEndLine() and
    ec = this.getEndColumn()
  }
}
