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
        var more_link = elements[i].parentElement.getElementsByClassName('text-truncate-toggle')[0];
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
    update_item = document.getElementById(item_name + '_update_item');
    update_item.classList.add('deleted');
    update_item.addEventListener('webkitAnimationEnd',
        function() {
            window.webkit.messageHandlers.updateOptionalInstallButtonFinishAction.postMessage(item_name)
        }
    );
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
        }
    );
}

function registerWindowClicks() {
    /* add an event listener for the More links and modal clicks */
    window.addEventListener('click',
        function(e) {
            if (e.target.classList.contains('text-truncate-toggle')) {
                // clicked a More link
                item_description = e.target.parentNode.getElementsByClassName('description')[0];
                item_version_and_size = e.target.parentNode.parentNode.getElementsByClassName('version_and_size')[0];
                modal_descritption = document.getElementById("fullDescription")
                modal_version_and_size = document.getElementById("versionAndSize")
                modal_descritption.innerHTML = item_description.innerHTML
                modal_version_and_size.innerHTML = item_version_and_size.innerHTML
                modal = document.getElementById("moreInfoModal");
                modal.style.display = "block";
                setTimeout(function(){modal.style.opacity = 1;}, 10);
                e.preventDefault();
            }
            if (e.target.classList.contains('close')) {
                // clicked the modal close button
                modal = document.getElementById("moreInfoModal");
                modal.style.opacity = 0;
                setTimeout(function(){modal.style.display = "none";}, 400);
                e.preventDefault();
            }
            if (e.target.classList.contains('modal')) {
                // clicked outside the modal content
                modal = document.getElementById("moreInfoModal");
                modal.style.opacity = 0;
                setTimeout(function(){modal.style.display = "none";}, 500);
                e.preventDefault();
            }
        }
    );
}

window.onload=function() {
    showOrHideMoreLinks();
    registerFadeInCleanup();
    registerWindowClicks();
}

window.onresize=function() {
    showOrHideMoreLinks();
}

window.onhaschange=function() {
    showOrHideMoreLinks();
}
