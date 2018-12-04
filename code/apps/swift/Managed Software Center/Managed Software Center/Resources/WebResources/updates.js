/* updates.js
   Managed Software Center
   
   Created by Greg Neagle on 12/28/13.
*/

Element.prototype.getElementHeight = function() {
    if (typeof this.clip !== "undefined") {
        return this.clip.height;
    } else {
        if (this.style.pixelHeight) {
            return this.style.pixelHeight;
        } else {
            return this.offsetHeight;
        }
    }
}

function showOrHideMoreLinks() {
    var elements = document.getElementsByClassName('description');
    for (var i = 0; i < elements.length; i++) {
        var truncated = (elements[i].getElementHeight() < elements[i].scrollHeight);
        var more_link = elements[i].getElementsByClassName('text-truncate-toggle')[0];
        if (truncated && more_link.classList.contains('hidden')) {
            more_link.classList.remove('hidden');
        }
        if (!(truncated) && !(more_link.classList.contains('hidden'))) {
            more_link.classList.add('hidden');
        }
    }
}

function fadeOutAndRemove(item_name) {
    /* add a class to trigger a CSS transition fade-out, then
       register a callback for when the transition completes so we can remove the item */
    update_table_row = document.getElementById(item_name + '_update_table_row');
    update_table_row.classList.add('deleted');
    update_table_row.addEventListener('webkitAnimationEnd',
        function() {
            window.webkit.messageHandlers.updateOptionalInstallButtonFinishAction.postMessage(item_name)
        });
}

function registerFadeInCleanup() {
    /* removes the 'added' class from table rows after their
       fadeIn animation completes */
    window.addEventListener('webkitAnimationEnd',
        function(e) {
            if (e.target.classList.contains('added')) {
                /* our newly-added table row */
                e.target.classList.remove('added');
            }
        });
}

function registerMoreLinkClick() {
    /* add an event listener for the More links */
    window.addEventListener('click',
        function(e) {
            if (e.target.classList.contains('text-truncate-toggle')) {
                description = e.target.parentNode;
                description.style.webkitLineClamp = "100%"
                e.target.classList.add('hidden');
                e.preventDefault();
            }
        });
}

window.onload=function() {
    showOrHideMoreLinks();
    registerFadeInCleanup();
    registerMoreLinkClick();
}

window.onresize=function() {
    showOrHideMoreLinks();
}

window.onhaschange=function() {
    showOrHideMoreLinks();
}
