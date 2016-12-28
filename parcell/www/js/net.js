/**
 * Created by krause on 2016-02-04.
 */
function Net(statusSel) {
  var that = this;
  var preDelay = 500;
  var fastDuration = 200;
  var fastEase = "easeInOutCubic";
  var req = 0;
  var status = statusSel.append("i").style({
    "animation-duration": "0.8s",
    "opacity": 0.0,
  }).classed({
    "fa": true,
    "fa-fw": true,
  });
  var multi = statusSel.append("span");

  var active = true;
  this.active = function(_) {
    if(!arguments.length) return active;
    active = _;
  };

  var otherReq = 0;
  this.otherReq = function(_) {
    if(!arguments.length) return otherReq;
    otherReq = +_;
    updateStatus();
  };

  function updateStatus() {
    if(req < 0 || otherReq < 0) {
      status.classed({
        "fa-frown-o": true,
        "fa-spin": false,
      }).transition().duration(fastDuration).ease(fastEase).style({
        "opacity": 1,
      });
    } else if(req + otherReq > 0) {
      status.classed({
        "fa-cog": true,
        "fa-spin": true,
      }).transition().duration(fastDuration).ease(fastEase).style({
        "opacity": 1,
      });
    } else {
      status.transition().duration(fastDuration).ease(fastEase).style({
        "opacity": 0,
      });
    }
    multi.text(req + otherReq > 1 && req >= 0 && otherReq >= 0 ? "x" + (req + otherReq) : "");
  };

  function busy() {
    if(req < 0) return;
    req += 1;
    updateStatus();
  }

  function normal() {
    if(req < 0) return;
    req -= 1;
    updateStatus();
  }

  function error() {
    req = -1;
    updateStatus();
  }

  var starts = {};
  function runStart(ref) {
    setTimeout(function() {
      if(!starts[ref]) return;
      busy();
      var s = starts[ref];
      starts[ref] = null;
      if(!(ref in actives)) {
        actives[ref] = 0;
      } else {
        actives[ref] += 1;
      }
      var cur = actives[ref];
      if(s["method"] === "GET") {
        d3.json(s["url"], function(err, data) {
          if(err) {
            console.warn("Failed loading " + ref);
            error();
            return console.warn(err);
          }
          if(cur !== actives[ref]) {
            normal();
            return;
          }
          var err = true;
          try {
            s["cb"](data);
            err = false;
          } finally {
            if(err) {
              error();
            } else {
              normal();
            }
          }
        });
      } else if(s["method"] === "GET_PLAIN") {
        d3.xhr(s["url"], function(err, data) {
          if(err) {
            console.warn("Failed loading " + ref);
            error();
            return console.warn(err);
          }
          var err = true;
          try {
            s["cb"](data["response"]);
            err = false;
          } finally {
            if(err) {
              error();
            } else {
              normal();
            }
          }
        });
      } else if(s["method"] === "POST") {
        d3.json(s["url"]).header("Content-Type", "application/json").post(s["obj"], function(err, data) {
          if(err) {
            console.warn("Failed loading " + ref);
            error();
            return console.warn(err);
          }
          if(cur !== actives[ref]) {
            normal();
            return;
          }
          var err = true;
          try {
            s["cb"](data);
            err = false;
          } finally {
            if(err) {
              error();
            } else {
              normal();
            }
          }
        });
      } else {
        console.warn("unknown method", s);
      }
    }, preDelay);
  }

  var actives = {};
  this.get = function(id, url, args, cb) {
    if(!active) return;
    var ref = "GET " + id;
    starts[ref] = {
      "method": "GET",
      "url": that.url(url, args),
      "cb": cb,
    };
    runStart(ref);
  }; // get

  this.getPlain = function(id, url, args, cb) {
    if(!active) return;
    var ref = "GET_PLAIN " + id;
    starts[ref] = {
      "method": "GET_PLAIN",
      "url": that.url(url, args),
      "cb": cb,
    };
    runStart(ref);
  }; // getPlain

  this.post = function(id, url, args, payload, cb) {
    if(!active) return;
    var ref = "POST " + id;
    var cur = actives[ref];
    var obj = JSON.stringify(payload);
    starts[ref] = {
      "method": "POST",
      "url": that.url(url, args),
      "cb": cb,
      "obj": obj,
    };
    runStart(ref);
  }; // post

  this.url = function(url, args) {
    return url + that.args(args);
  }; // url

  this.args = function(args) {
    return Object.keys(args).reduce(function(str, val, ix) {
      if(args[val] === null) {
        return str;
      }
      str += str.length ? "&" : "?";
      str += encodeURIComponent(val);
      str += "=";
      str += encodeURIComponent(args[val]);
      return str;
    }, "");
  }; // args

  this.getProject = function(args) {
    var project = args["project"] || "";
    if(!project) {
      args["next"] = window.location.pathname;
      window.location = that.url("project_select.html", args);
    }
    return project;
  }; // getProject

  this.returnProject = function(urlArgs, project) {
    var landing = urlArgs["next"] || "index.html";
    var args = {};
    Object.keys(urlArgs).forEach(function(key) {
      if(key === "next") return;
      args[key] = urlArgs[key];
    });
    args["project"] = project;
    window.location = that.url(landing, args);
  }; // returnProject
} // Net
