/**
 * Created by krause on 2016-01-26.
 */
function List(sel) {
  var that = this;
  var list = sel.style({
    "overflow-y": "scroll",
  }).append("ul").classed("list_ul", true);

  var selectId = null;
  this.selectId = function(_) {
    if(!arguments.length) return selectId;
    selectId = _;
  };

  var scrollTo = false;
  this.scrollToSelect = function(_) {
    if(!arguments.length) return scrollTo;
    scrollTo = _;
  };

  var elements = [];
  this.elements = function(_) {
    if(!arguments.length) return elements;
    elements = _;
  };

  var onClick = null;
  this.onClick = function(_) {
    if(!arguments.length) return onClick;
    onClick = _;
  };

  var onEnter = null;
  this.onEnter = function(_) {
    if(!arguments.length) return onEnter;
    onEnter = _;
  };

  var onUpdate = null;
  this.onUpdate = function(_) {
    if(!arguments.length) return onUpdate;
    onUpdate = _;
  };

  var hasId = null;
  this.hasId = function(_) {
    if(!arguments.length) return hasId;
    hasId = _;
  };

  this.getElement = function(id) {
    return elements.reduce(function(p, v) {
      return hasId && hasId(v, id) ? v : p;
    }, null);
  };

  this.listSel = function() {
    return list;
  };

  this.update = function() {
    var ixs = elements.map(function(_, ix) {
      return ix;
    });

    function get(ix) {
      return elements[ix];
    }

    var lis = list.selectAll("li.list_li").data(ixs, function(ix) {
      return ix;
    });
    lis.exit().remove();
    var lise = lis.enter().append("li").classed("list_li", true);
    onEnter && onEnter(lise, get);
    lis.classed({
      "list_li_sel": function(ix) {
        var isSel = hasId && hasId(get(ix), selectId);
        if(isSel && scrollTo) {
          var el = this;
          var body = d3.select("body").node();
          var oldScroll = body.scrollTop;
          if(el.scrollIntoViewIfNeeded) {
            el.scrollIntoViewIfNeeded();
          } else {
            el.scrollIntoView();
          }
          body.scrollTop = oldScroll;
          scrollTo = false;
        }
        return isSel;
      },
      "clickable": function() {
        return !!onClick;
      }
    }).on("click", function(ix) {
      onClick && onClick(get(ix));
    }).order();
    onUpdate && onUpdate(lis, get);
  };

} // List
