# CardDemo through c3270: a user updates an account, an admin adds, updates and deletes a user. Run by carddemo_3270_video.sh.
Require c3270

Set Shell "bash"
Set FontSize 20
Set Columns 80
Set Rows 25
Set Padding 24
Set Theme "Builtin Dark"
Set TypingSpeed 140ms
Set WaitTimeout 60s
Set Framerate 30

Hide
Type 'c3270 "$CARDDEMO_C3270_SESSION"'
Enter
Wait+Screen /Type your User ID/
Show
Sleep 3.5s

Type "USER0001"
Type "PASSWORD"
Sleep 0.8s
Enter
Wait+Screen /Main Menu/
Sleep 3.5s

Type "01"
Enter
Wait+Screen /View Account/
Sleep 1.5s
Type "00000000001"
Enter
Wait+Screen /Kessler/
Sleep 5.5s
Ctrl+P
Type "3"
Wait+Screen /Main Menu/
Sleep 2s

Type "02"
Enter
Wait+Screen /Update Account/
Sleep 1.5s
Type "00000000001"
Enter
Wait+Screen /Update account details presented above/
Sleep 4.5s
Tab@40ms 36
Sleep 0.8s
Type "2125550100"
Sleep 1.5s
Enter
Wait+Screen /FICO Score: should be between/
Sleep 5s
Type "720"
Tab@80ms 6
Type "27601"
Sleep 1.5s
Enter
Wait+Screen /Changes validated/
Sleep 4.5s
Ctrl+P
Type "5"
Wait+Screen /Changes committed to database/
Sleep 4.5s
Ctrl+P
Type "3"
Wait+Screen /Main Menu/
Sleep 2s

Type "01"
Enter
Wait+Screen /View Account/
Sleep 1.5s
Type "00000000001"
Enter
Wait+Screen /\(212\)555-0100/
Sleep 6s
Ctrl+P
Type "3"
Wait+Screen /Main Menu/
Sleep 2s
Ctrl+P
Type "3"
Wait+Screen /Thank you for using CardDemo/
Sleep 3.5s

Ctrl+A
Type "c"
Sleep 1.5s
Type "CC00"
Enter
Wait+Screen /Type your User ID/
Sleep 2s
Type "ADMIN001"
Type "PASSWORD"
Sleep 0.8s
Enter
Wait+Screen /Admin Menu/
Sleep 3.5s

Type "01"
Enter
Wait+Screen /List Users/
Sleep 5.5s
Ctrl+P
Type "3"
Wait+Screen /Admin Menu/
Sleep 1.5s

Type "02"
Enter
Wait+Screen /Add User/
Sleep 1.5s
Type "CAROL"
Tab
Type "DIAZ"
Tab
Type "USER0006"
Type "PASSWORD"
Type "U"
Sleep 1.5s
Enter
Wait+Screen /User USER0006 has been added/
Sleep 4.5s
Ctrl+P
Type "3"
Wait+Screen /Admin Menu/
Sleep 1.5s

Type "01"
Enter
Wait+Screen /List Users/
Sleep 1.5s
Type "USER0001"
Enter
Wait+Screen /USER0006 +CAROL/
Sleep 5.5s
Ctrl+P
Type "3"
Wait+Screen /Admin Menu/
Sleep 1.5s

Type "03"
Enter
Wait+Screen /Update User/
Sleep 1.5s
Type "USER0006"
Enter
Wait+Screen /Press PF5 key to save your updates/
Sleep 3.5s
Tab
Ctrl+U
Type "CAROLINE"
Tab
Ctrl+U
Type "DIAZ"
Tab
Type "PASSWORD"
Type "U"
Sleep 1.5s
Ctrl+P
Type "5"
Wait+Screen /User USER0006 has been updated/
Sleep 5s
Ctrl+P
Type "3"
Wait+Screen /Admin Menu/
Sleep 1.5s

Type "04"
Enter
Wait+Screen /Delete User/
Sleep 1.5s
Type "USER0006"
Enter
Wait+Screen /Press PF5 key to delete this user/
Sleep 5s
Ctrl+P
Type "5"
Wait+Screen /User USER0006 has been deleted/
Sleep 4.5s
Ctrl+P
Type "3"
Wait+Screen /Admin Menu/
Sleep 1.5s

Type "01"
Enter
Wait+Screen /List Users/
Sleep 1.5s
Type "USER0001"
Enter
Wait+Screen /----\s+USER0001 +LAWRENCE/
Sleep 7s
