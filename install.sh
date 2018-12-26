#!/usr/bin/env bash
# Domoticz Phicomm M1 Receiver Plugins
# (c) 2018 by xiaoyao9184
# https://github.com/xiaoyao9184/Phicomm-M1-Domoticz-Plugin
# Installs Domoticz Phicomm M1 Receiver Plugins
#
# Domoticz Phicomm M1 Receiver Plugins is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.

# Donations are welcome via the website or application
#
# Install with this command (from your Pi):
#
# curl -L https://github.com/xiaoyao9184/Phicomm-M1-Domoticz-Plugin/raw/master/install.sh | bash

set -e
######## VARIABLES #########
setupVars=/etc/domoticz/setupVars.conf

useUpdateVars=false

Dest_folder=""
Temp_folder="/tmp/Phicomm-M1-Domoticz-Plugin"


lowercase(){
    echo "$1" | sed "y/ABCDEFGHIJKLMNOPQRSTUVWXYZ/abcdefghijklmnopqrstuvwxyz/"
}

OS=`lowercase \`uname -s\``
MACH=`uname -m`
if [ ${MACH} = "armv6l" ]
then
 MACH="armv7l"
fi

# Find the rows and columns will default to 80x24 is it can not be detected
screen_size=$(stty size 2>/dev/null || echo 24 80) 
rows=$(echo $screen_size | awk '{print $1}')
columns=$(echo $screen_size | awk '{print $2}')

# Divide by two so the dialogs take up half of the screen, which looks nice.
r=$(( rows / 2 ))
c=$(( columns / 2 ))
# Unless the screen is tiny
r=$(( r < 20 ? 20 : r ))
c=$(( c < 70 ? 70 : c ))

######## FIRST CHECK ########
# Must be root to install
echo ":::"
if [[ ${EUID} -eq 0 ]]; then
	echo "::: You are root."
else
	echo "::: Script called with non-root privileges. The Domoticz Phicomm M1 Receiver Plugin installs server packages and configures"
	echo "::: system networking, it requires elevated rights. Please check the contents of the script for"
	echo "::: any concerns with this requirement. Please be sure to download this script from a trusted source."
	echo ":::"
	echo "::: Detecting the presence of the sudo utility for continuation of this install..."

	if [ -x "$(command -v sudo)" ]; then
		echo "::: Utility sudo located."
		exec curl -sSL https://github.com/xiaoyao9184/Phicomm-M1-Domoticz-Plugin/raw/master/install.sh | sudo bash "$@"
		exit $?
	else
		echo "::: sudo is needed for the Web interface to run domoticz commands.  Please run this script as root and it will be automatically installed."
		exit 1
	fi
fi

# Compatibility

if [ -x "$(command -v apt-get)" ]; then
	#Debian Family
	#############################################
	PKG_MANAGER="apt-get"
	PKG_CACHE="/var/lib/apt/lists/"
	UPDATE_PKG_CACHE="${PKG_MANAGER} update"
	PKG_UPDATE="${PKG_MANAGER} upgrade"
	PKG_INSTALL="${PKG_MANAGER} --yes --fix-missing install"
	# grep -c will return 1 retVal on 0 matches, block this throwing the set -e with an OR TRUE
	PKG_COUNT="${PKG_MANAGER} -s -o Debug::NoLocking=true upgrade | grep -c ^Inst || true"
	INSTALLER_DEPS=( libffi-dev libssl-dev git python3 python3-pip)
    PYTHON_DEPS=( python-miio ptvsd rpdb )
    package_check_install() {
		dpkg-query -W -f='${Status}' "${1}" 2>/dev/null | grep -c "ok installed" || ${PKG_INSTALL} "${1}"
	}
    PIP_INSTALL="pip3 install"
	pip_install_list=$(pip3 list --format=columns)
    pip_check_install() {
		echo $pip_install_list | grep -c "${1}" || ${PIP_INSTALL} "$@"
    }
else
	echo "OS distribution not supported"
	exit
fi

####### FUNCTIONS ##########
spinner() {
	local pid=$1
	local delay=0.50
	local spinstr='/-\|'
	while [ "$(ps a | awk '{print $1}' | grep "${pid}")" ]; do
		local temp=${spinstr#?}
		printf " [%c]  " "${spinstr}"
		local spinstr=${temp}${spinstr%"$temp"}
		sleep ${delay}
		printf "\b\b\b\b\b\b"
	done
	printf "    \b\b\b\b"
}

find_current_user() {
	# Find current user
	Current_user=${SUDO_USER:-$USER}
	echo "::: Current User: ${Current_user}"
}

find_IPv4_information() {
	# Find IP used to route to outside world
	IPv4dev=$(ip route get 8.8.8.8 | awk '{for(i=1;i<=NF;i++)if($i~/dev/)print $(i+1)}')
	IPv4_address=$(ip -o -f inet addr show dev "$IPv4dev" | awk '{print $4}' | awk 'END {print}')
	IPv4gw=$(ip route get 8.8.8.8 | awk '{print $3}')
}

welcomeDialogs() {
	# Display the welcome dialog
	whiptail --msgbox --backtitle "Welcome" --title "Domoticz Phicomm M1 Receiver Plugin automated installer" "\n\nThis installer will install xiaomi plugin to your Domoticz!\n\n
Domoticz Phicomm M1 Receiver Plugin is free\n\n
Domoticz Phicomm M1 Receiver Plugin needs a setting device to send data to Domoticz IP, 
you can use 'dnsmasq' with setting 'address=/.aircat.phicomm.com/$IPv4gw' on the router to make it happen.
	" ${r} ${c}
}

displayFinalMessage() {
	# Final completion message to user
	whiptail --msgbox --backtitle "Ready..." --title "Installation Complete!" "Go to Domoticz and add plugin.

Github:  https://github.com/xiaoyao9184/Phicomm-M1-Domoticz-Plugin" ${r} ${c}
}

chooseServices() {
    cd "$Temp_folder/Phicomm-M1-Domoticz-Plugin"
    index=0
    indexs=()
    options=()
    for d in */; do
        indexs[index]=$d
        i=$((index * 3))
        options[i]=${d}
        options[$((i + 1))]="Enable plugin ${d}"
        options[$((i + 2))]=on
        index=$((index + 1))
    done
    echo "::: Find ${#indexs[*]} plugins in $Temp_folder/Phicomm-M1-Domoticz-Plugin"
    
	cmd=(whiptail --separate-output --checklist "Select Plugin (press space to select)" ${r} ${c} ${#indexs[*]})
	choices=$("${cmd[@]}" "${options[@]}" 2>&1 >/dev/tty)
	if [[ $? = 0 ]];then
	    count=0
		for choice in ${choices}
		do
            echo ":::     Choice install plugin ${choice}"
			count=$((count + 1))
		done
        if [ ${count} -eq 0 ]; then
			echo "::: Cannot continue, nothing plugins selected"
			echo "::: Exiting"
			exit 1
		fi
	else
		echo "::: Cancel selected. Exiting..."
		exit 1
	fi
}

chooseDestinationFolder() {
	Dest_folder=$(whiptail --inputbox "Domoticz Folder:" ${r} ${c} ${Dest_folder} --title "Destination" 3>&1 1>&2 2>&3)
	exitstatus=$?
	if [ $exitstatus = 0 ]; then
		echo ":::"
	else
		echo "::: Cancel selected. Exiting..."
		exit 1
	fi	
}

stop_service() {
	# Stop service passed in as argument.
	echo ":::"
	echo -n "::: Stopping ${1} service..."
	if [ -x "$(command -v service)" ]; then
		service "${1}" stop &> /dev/null & spinner $! || true
	fi
	echo " done."
}

start_service() {
	# Start/Restart service passed in as argument
	# This should not fail, it's an error if it does
	echo ":::"
	echo -n "::: Starting ${1} service..."
	if [ -x "$(command -v service)" ]; then
		service "${1}" restart &> /dev/null  & spinner $!
	fi
	echo " done."
}

update_package_cache() {
	#Running apt-get update/upgrade with minimal output can cause some issues with
	#requiring user input (e.g password for phpmyadmin see #218)

	#Check to see if apt-get update has already been run today
	#it needs to have been run at least once on new installs!
	timestamp=$(stat -c %Y ${PKG_CACHE})
	timestampAsDate=$(date -d @"${timestamp}" "+%b %e")
	today=$(date "+%b %e")

	if [ ! "${today}" == "${timestampAsDate}" ]; then
		#update package lists
		echo ":::"
		echo -n "::: ${PKG_MANAGER} update has not been run today. Running now..."
		${UPDATE_PKG_CACHE} &> /dev/null & spinner $!
		echo " done!"
	fi
}

notify_package_updates_available() {
  # Let user know if they have outdated packages on their system and
  # advise them to run a package update at soonest possible.
	echo ":::"
	echo -n "::: Checking ${PKG_MANAGER} for upgraded packages...."
	updatesToInstall=$(eval "${PKG_COUNT}")
	echo " done!"
	echo ":::"
	if [[ ${updatesToInstall} -eq "0" ]]; then
		echo "::: Your system is up to date! Continuing with Domoticz installation..."
	else
		echo "::: There are ${updatesToInstall} updates available for your system!"
		echo "::: We recommend you run '${PKG_UPDATE}' after installing Domoticz! "
		echo ":::"
	fi
}

install_dependent_packages() {
	# Install packages passed in via argument array
	# No spinner - conflicts with set -e
	declare -a argArray1=("${!1}")

	for i in "${argArray1[@]}"; do
		echo -n ":::    Checking for $i..."
		package_check_install "${i}" &> /dev/null
		echo " installed!"
	done
}

install_python_packages() {
    ua=( pip setuptools )
    for i in "${ua[@]}"; do
		echo -n ":::    Checking for python $i..."
        pip_check_install "${i}" "-U" 1> /dev/null
		echo " installed!"
	done
	# Install packages passed in via argument array
	# No spinner - conflicts with set -e
	declare -a argArray1=("${!1}")
	for i in "${argArray1[@]}"; do
		echo -n ":::    Checking for python $i..."
        pip_check_install "${i}" 1> /dev/null
		echo " installed!"
	done
}

install_packages() {
	# Update package cache
	update_package_cache

	# Notify user of package availability
	notify_package_updates_available

	# Install packages used by this installation script
	install_dependent_packages INSTALLER_DEPS[@]

	# Install packages used by the Domoticz
	install_python_packages PYTHON_DEPS[@]
}

downloadDomoticzPlugin() {
    if [[ -e $Temp_folder ]]; then
        rm -f -r $Temp_folder
	fi
    echo "::: Creating ${Temp_folder}"
    mkdir $Temp_folder
    cd $Temp_folder
    # Get plugin
    echo "::: Clone github"
    git clone https://github.com/xiaoyao9184/Phicomm-M1-Domoticz-Plugin &> /dev/null
    cd "./Phicomm-M1-Domoticz-Plugin"
}

installDomoticzPlugin() {
    cd "$Temp_folder/Phicomm-M1-Domoticz-Plugin"
    if [[ ! -e "${Dest_folder}/plugins/" ]]; then
        mkdir "${Dest_folder}/plugins/"
        chown "${Current_user}":"${Current_user}" "${Dest_folder}/plugins/"
	fi
    # Move plugin
    echo "::: Destination folder=${Dest_folder}/plugins/"
    for d in */; do
		if echo "${choices[@]}" | grep -w "$d" &>/dev/null; then
			echo -n ":::     Move plugin ${d}..."
			cp -a $d "${Dest_folder}/plugins/"
			chown "${Current_user}":"${Current_user}" "${Dest_folder}/plugins/${d}"
			echo " done!"
		fi
    done
    
    # Remove temp files
	rm -f -r $Temp_folder
}

main() {
    install_packages

	downloadDomoticzPlugin

	find_current_user

	find_IPv4_information
	
	Dest_folder="/home/${Current_user}/domoticz"

	if [[ -f ${setupVars} ]]; then
		useUpdateVars=false
    else
        echo "Domoticz not installed!"
	    exit
	fi
		
	if [[ ${useUpdateVars} == false ]]; then
		# Display welcome dialogs
		welcomeDialogs
		# Install and log everything to a file
		chooseServices
		chooseDestinationFolder
		installDomoticzPlugin
	fi

	if [[ "${useUpdateVars}" == false ]]; then
	    displayFinalMessage
	fi

	echo "::: Restarting services..."
	# ReStart services
    cd ${Dest_folder}
	stop_service domoticz.sh
	start_service domoticz.sh
	echo "::: done."

	echo ":::"
	if [[ "${useUpdateVars}" == false ]]; then
		echo "::: Installation Complete!"
	else
		echo "::: Update complete!"
	fi
}

main "$@"