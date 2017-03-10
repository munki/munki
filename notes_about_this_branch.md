### Introduction
This branch contains a re-think of the repo plugin support.

repo plugins are in munkilib/munkirepo.

FileRepo is the default plugin and handles both local file repos and repos hosted on fileshares.

MWA2APIRepo is a proof-of-concept plugin that talks to a remote repo via the MWA2 API. It requires the latest MWA2 code from GitHub.

### Command-line tools
These command-line admin tools have been updated to use the new-style repo plugins:

`iconimporter`  
`makecatalogs`  
`manifestutil`  
`munkiimport`  

When using the `--configure` option with `manifestutil` and `munkiimport`, there are three major changes to be aware of:

- You will no longer be prompted for a repo path. This preference may be deprecated in the future -- I'm not sure it's needed any longer.

- Repo URL can take several forms:
   - a file: url: file:///Users/Shared/munki\_repo will cause these tools to use a local file-based repo located at /Users/Shared/munki_repo
   - a filesharing url: afp://someserver/sharename or smb://someserver/sharename or nfs://someserver/sharename These tools will attempt to mount these URLs and use whatever mountpoint they mount at (typically under /Volumes)
   - An http/https url: Example: https://mwa2.my.org/api These sorts of repos require a custom plugin that knows how to talk to the repo at the given URL.

- You will be prompted for a plugin name. For traditional file-based repos (either local or those available via fileshare, the default FileRepo plugin can be used. If plugin is not defined, the FileRepo plugin will be used.)

### Workflow changes
The most noticable change to workflows using the modified tools is around editing pkginfo items in a text editor when using munkiimport.

Since we can't guarantee direct file access to the pkginfo item after it's been uploaded to the Munki repo, we ask _before_ we upload it if you want to edit it.

If you answer 'yes', the pkginfo is opened in your editor of choice. 
- If the editor is command-line based (like vi), once you exit the editor, the munkiimport session will resume and the pkginfo file will be uploded to the repo.
- If the editor is an application (like SublimeText), munkiimport will wait for you to manually indicate you are done editing the file before proceeding.
- The pkginfo is saved to a temp file before it is opened in the text editor, so don't be concerned about the strange path you might see.

### Other notes
`makecatalogs` works with the MWA2APIRepo but is very, very slow due to all the web calls neeed to get every icon and pkginfo item. A future version of the code will allow a plugin to tell the repo to makecatalogs itself: so for the MWA2API, it would trigger the MWA2 code to do the catalog rebuild.

`iconimporter` has to download dmgs and pkgs from the repo in order to process them for possible icons. This is slower and uses more disk than the direct file access possible when only file-based repos were supported. Running `iconimporter` against an entire repo should be an infrequent operation, so it's not likely this is worth optimizing in any way.

### Plugin developer notes
The "API" of the new-style repo plugins is greatly simplified over the previous style of repo plugins. It's possible I've over-simplfied it and it might need extension to cover things I haven't thought of. See the munkilib/munkirepo/FileRepo.py and munkilib/munkirepo/MWA2APIRepo.py files for concrete examples of the new-style repo plugins.
