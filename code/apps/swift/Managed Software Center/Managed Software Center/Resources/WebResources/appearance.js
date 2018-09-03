/* appearance.js
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
