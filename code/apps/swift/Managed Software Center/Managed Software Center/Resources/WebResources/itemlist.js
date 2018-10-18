/* itemlist.js
 Managed Software Center
 
 Created by Greg Neagle on 12/28/13.
 */

function category_select() {
    var e = document.getElementById("category-selector");
    var category = e.options[e.selectedIndex].text;
    window.webkit.messageHandlers.changeSelectedCategory.postMessage(category);
}
