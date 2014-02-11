/* itemlist.js
 Managed Software Update
 
 Created by Greg Neagle on 12/28/13.
 */

function category_select() {
    var e = document.getElementById("category-selector");
    var category = e.options[e.selectedIndex].text;
    window.AppController.changeSelectedCategory_(category);
}

var currentSlide = 0, playing = 1

function slides(){
    return document.querySelectorAll('div.stage>img')
}

function showSlide(slideNumber){
    theSlides = slides()
    for (c=0; c<theSlides.length; c++) {
        theSlides[c].style.opacity="0";
    }
    theSlides[slideNumber].style.opacity="1";
}

function showNextSlide(){
    if (playing) {
        currentSlide = (currentSlide > slides().length-2) ? 0 : currentSlide + 1;
        showSlide(currentSlide);
    }
}

function stageClicked() {
    slide = slides()[currentSlide];
    window.location.href = slide.getAttribute('href');
}

window.onload=function(){
    showSlide(0);
    if (slides().length > 1) {
        setInterval(showNextSlide, 5000);
    }
}
