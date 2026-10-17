property script_py : "@@SCRIPT@@"
property py : "/opt/homebrew/bin/python3"

on run
	my lancer("")
end run

on open fichiers
	repeat with f in fichiers
		my lancer(quoted form of POSIX path of f)
	end repeat
end open

on lancer(arg)
	try
		do shell script "export PATH=/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin; " & quoted form of py & " -I " & quoted form of script_py & " " & arg
	on error msg
		display dialog "L'impression n'a pas abouti :" & return & msg with title "Étiquette Chronopost RP425" buttons {"OK"} default button "OK" with icon stop
	end try
end lancer
