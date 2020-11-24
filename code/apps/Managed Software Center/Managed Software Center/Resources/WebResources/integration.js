/* integration.js
 Managed Software Center
 
 Created by Greg Neagle on 8/27/18.
 */

function changeAppearanceModeTo(theme) {
    document.documentElement.classList.add('appearance-transition')
    document.documentElement.setAttribute('data-theme', theme)
    window.setTimeout(function() {
                         document.documentElement.classList.remove('appearance-transition')
                      }, 1000)
}

// integration functions to be called from Swift

function b64DecodeUnicode(str) {
    return decodeURIComponent(Array.prototype.map.call(atob(str), function(c) {
        return '%' + ('00' + c.charCodeAt(0).toString(16)).slice(-2)
    }).join(''))
}

function setInnerHTMLforElementID(elementID, encodedData) {
    var theElement = document.getElementById(elementID);
    if (theElement != null) {
        var decodedData = b64DecodeUnicode(encodedData);
        theElement.innerHTML = decodedData;
    }
}

function addToInnerHTMLforElementID(elementID, encodedData) {
    var theElement = document.getElementById(elementID);
    if (theElement != null) {
        var decodedData = b64DecodeUnicode(encodedData);
        theElement.innerHTML = theElement.innerHTML + decodedData;
    }
}

function setInnerTextforElementID(elementID, encodedData) {
    var theElement = document.getElementById(elementID);
    if (theElement != null) {
        var decodedData = b64DecodeUnicode(encodedData);
        theElement.innerText = decodedData;
    }
}

function removeElementByID(elementID) {
    var elem = document.getElementById(elementID);
    if (elem != null) {
        elem.parentNode.removeChild(elem);
        return true;
    }
    return false;
}

// status update functions

function updateProgress(percent_done) {
    var progress_bar = document.getElementById("progress-bar");
    if (progress_bar != null) {
        progress_bar.parentElement.classList.remove("hidden");
        if (Number(percent_done) < 0) {
            progress_bar.removeAttribute("value");
        } else {
            progress_bar.setAttribute("value", percent_done.toString());
        }
    }
}

function hideStopButton() {
    var install_btn = document.getElementById("install-all-button-text");
    if (install_btn != null) {
        install_btn.classList.add("hidden");
    }
}

function showStopButton() {
    var install_btn = document.getElementById("install-all-button-text");
    if (install_btn != null) {
        install_btn.classList.remove("hidden");
    }
}

function disableStopButton() {
    var install_btn = document.getElementById("install-all-button-text");
    if (install_btn != null) {
        install_btn.classList.add("disabled");
    }
}

function enableStopButton() {
    var install_btn = document.getElementById("install-all-button-text");
    if (install_btn != null) {
        install_btn.classList.remove("disabled");
    }
}
